# Copyright 2013 Rackspace, Inc.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#   http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import collections
import copy
import glob
import os
import shutil
import tempfile

from oslo_concurrency import processutils
from oslo_log import log as logging
from six.moves.urllib import parse

from ironic_python_agent import errors
from ironic_python_agent.openstack.common import _i18n as gtu

LOG = logging.getLogger(__name__)


SUPPORTED_ROOT_DEVICE_HINTS = set(('size', 'model', 'wwn', 'serial', 'vendor'))

# Agent parameters can be pased by kernel command-line arguments and/or
# by virtual media. Virtual media parameters passed would be available
# when the agent is started, but might not be available for re-reading
# later on because:
# * Virtual media might be exposed from Swift and swift temp url might
#   expire.
# * Ironic might have removed the floppy image from Swift after starting
#   the deploy.
#
# Even if it's available, there is no need to re-read from the device and
# /proc/cmdline again, because it is never going to change.  So we cache the
# agent parameters that was passed (by proc/cmdline and/or virtual media)
# when we read it for the first time, and then use this cache.
AGENT_PARAMS_CACHED = dict()


def get_ordereddict(*args, **kwargs):
    """A fix for py26 not having ordereddict."""
    try:
        return collections.OrderedDict(*args, **kwargs)
    except AttributeError:
        import ordereddict
        return ordereddict.OrderedDict(*args, **kwargs)


def execute(*cmd, **kwargs):
    """Convenience wrapper around oslo's execute() method."""
    result = processutils.execute(*cmd, **kwargs)
    LOG.debug(gtu._('Execution completed, command line is "%s"'),
              ' '.join(cmd))
    LOG.debug(gtu._('Command stdout is: "%s"') % result[0])
    LOG.debug(gtu._('Command stderr is: "%s"') % result[1])
    return result


def _read_params_from_file(filepath):
    """Extract key=value pairs from a file.

    :param filepath: path to a file containing key=value pairs separated by
                     whitespace or newlines.
    :returns: a dictionary representing the content of the file
    """
    with open(filepath) as f:
        cmdline = f.read()

    options = cmdline.split()
    params = {}
    for option in options:
        if '=' not in option:
            continue
        k, v = option.split('=', 1)
        params[k] = v

    return params


def _get_vmedia_device():
    """Finds the device filename of the virtual media device using sysfs.

    :returns: a string containing the filename of the virtual media device
    """
    sysfs_device_models = glob.glob("/sys/class/block/*/device/model")
    vmedia_device_model = "virtual media"
    for model_file in sysfs_device_models:
        try:
            with open(model_file) as model_file_fobj:
                if vmedia_device_model in model_file_fobj.read().lower():
                    vmedia_device = model_file.split('/')[4]
                    return vmedia_device
        except Exception:
            pass


def _get_vmedia_params():
    """This method returns the parameters passed through virtual media floppy.

    :returns: a partial dict of potential agent configuration parameters
    :raises: VirtualMediaBootError when it cannot find the virtual media device
    """
    parameters_file = "parameters.txt"

    vmedia_device_file = "/dev/disk/by-label/ir-vfd-dev"
    if not os.path.exists(vmedia_device_file):

        # TODO(rameshg87): This block of code is there only for compatibility
        # reasons (so that newer agent can work with older Ironic). Remove
        # this after Liberty release.
        vmedia_device = _get_vmedia_device()
        if not vmedia_device:
            msg = "Unable to find virtual media device"
            raise errors.VirtualMediaBootError(msg)

        vmedia_device_file = os.path.join("/dev", vmedia_device)

    vmedia_mount_point = tempfile.mkdtemp()
    try:
        try:
            stdout, stderr = execute("mount", vmedia_device_file,
                                     vmedia_mount_point)
        except processutils.ProcessExecutionError as e:
            msg = ("Unable to mount virtual media device %(device)s: "
                   "%(error)s" % {'device': vmedia_device_file, 'error': e})
            raise errors.VirtualMediaBootError(msg)

        parameters_file_path = os.path.join(vmedia_mount_point,
                                            parameters_file)
        params = _read_params_from_file(parameters_file_path)

        try:
            stdout, stderr = execute("umount", vmedia_mount_point)
        except processutils.ProcessExecutionError as e:
            pass
    finally:
        try:
            shutil.rmtree(vmedia_mount_point)
        except Exception as e:
            pass

    return params


def _get_cached_params():
    """Helper method to get cached params to ease unit testing."""
    return AGENT_PARAMS_CACHED


def _set_cached_params(params):
    """Helper method to set cached params to ease unit testing."""
    global AGENT_PARAMS_CACHED
    AGENT_PARAMS_CACHED = params


def get_agent_params():
    """Gets parameters passed to the agent via kernel cmdline or vmedia.

    Parameters can be passed using either the kernel commandline or through
    virtual media. If boot_method is vmedia, merge params provided via vmedia
    with those read from the kernel command line.

    Although it should never happen, if a variable is both set by vmedia and
    kernel command line, the setting in vmedia will take precedence.

    :returns: a dict of potential configuration parameters for the agent
    """

    # Check if we have the parameters cached
    params = _get_cached_params()
    if not params:
        params = _read_params_from_file('/proc/cmdline')

        # If the node booted over virtual media, the parameters are passed
        # in a text file within the virtual media floppy.
        if params.get('boot_method') == 'vmedia':
            vmedia_params = _get_vmedia_params()
            params.update(vmedia_params)

        # Cache the parameters so that it can be used later on.
        _set_cached_params(params)

    return copy.deepcopy(params)


def normalize(string):
    """Return a normalized string."""
    # Since we can't use space on the kernel cmdline, Ironic will
    # urlencode the values.
    return parse.unquote(string).lower().strip()


def parse_root_device_hints():
    """Parse the root device hints.

    Parse the root device hints given by Ironic via kernel cmdline
    or vmedia.

    :returns: A dict with the hints or an empty dict if no hints are
              passed.
    :raises: DeviceNotFound if there are unsupported hints.

    """
    root_device = get_agent_params().get('root_device')
    if not root_device:
        return {}

    hints = dict((item.split('=') for item in root_device.split(',')))

    # Find invalid hints for logging
    not_supported = set(hints) - SUPPORTED_ROOT_DEVICE_HINTS
    if not_supported:
        error_msg = ('No device can be found because the following hints: '
                     '"%(not_supported)s" are not supported by this version '
                     'of IPA. Supported hints are: "%(supported)s"',
                    {'not_supported': ', '.join(not_supported),
                     'supported': ', '.join(SUPPORTED_ROOT_DEVICE_HINTS)})
        raise errors.DeviceNotFound(error_msg)

    # Normalise the values
    hints = {k: normalize(v) for k, v in hints.iteritems()}

    if 'size' in hints:
        # NOTE(lucasagomes): Ironic should validate before passing to
        # the deploy ramdisk
        hints['size'] = int(hints['size'])

    return hints
