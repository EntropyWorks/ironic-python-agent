===============================
Welcome to Ironic Python Agent!
===============================

Overview
========

Ironic Python Agent is an agent for controlling and deploying Ironic controlled
baremetal nodes. Typically run in a ramdisk, the agent exposes a REST API for
provisioning servers.

Throughout the remainder of the document, Ironic Python Agent will be
abbreviated to IPA.

How it works
============

Integration with Ironic
-----------------------

Compatible Deploy Drivers
~~~~~~~~~~~~~~~~~~~~~~~~~

Agent Deploy Driver
<<<<<<<<<<<<<<<<<<<
IPA works with the agent Deploy driver in Ironic to provision nodes. Starting
with ironic-python-agent running on a ramdisk on an unprovisioned node,
Ironic makes API calls to ironic-python-agent to provision the machine. This
allows for greater control and flexibility of the entire deployment process.

PXE Deploy Driver
<<<<<<<<<<<<<<<<<
IPA may also be used with the original Ironic pxe driver as of the Kilo
OpenStack Ironic release.

Configuring Deploy Drivers
<<<<<<<<<<<<<<<<<<<<<<<<<<
For information on how to install and configure Ironic drivers, including
drivers for IPA, see the Ironic drivers documentation [0]_.

Lookup
~~~~~~
On startup, the agent performs a lookup in Ironic to determine its node UUID
by sending a hardware profile to the Ironic vendor_passthru lookup endpoint:
``/v1/nodes/{node_ident}/vendor_passthru/lookup``.

Heartbeat
~~~~~~~~~
After successfully looking up its node, the agent heartbeats via
``/v1/nodes/{node_ident}/vendor_passthru/heartbeat`` every N seconds, where
N is the Ironic conductor's agent.heartbeat_timeout value multiplied by a
number between .3 and .6.

For example, if your conductor's ironic.conf contains::

  [agent]
  heartbeat_timeout = 60

IPA will heartbeat between every 20 and 36 seconds. This is to ensure jitter
for any agents reconnecting after a network or API disruption.

After the agent heartbeats, the conductor performs any actions needed against
the node, including querying status of an already run command. For example,
initiating in-band cleaning tasks or deploying an image to the node.

Image Builders
--------------
Unlike most other python software, you must build an IPA ramdisk image before
use. This is because it's not installed in an operating system, but instead is
run from within a ramdisk.

CoreOS
~~~~~~
The only current supported ramdisk image for IPA is the CoreOS image [1]_.
Prebuilt copies of the CoreOS image, suitable for pxe, are available on
`tarballs.openstack.org <http://tarballs.openstack.org/ironic-python-agent/coreos/files/>`__.

Build process
<<<<<<<<<<<<<
On a high level, the build steps are as follows:

1) A docker build is performed using the ``Dockerfile`` in the root of the
   ironic-python-agent project.
2) The resulting docker image is exported to a filesystem image.
3) The filesystem image, along with a cloud-config.yml [2]_, are embedded into
   the CoreOS PXE image at /usr/share/oem/.
4) On boot, the ironic-python-agent filesystem image is extracted and run
   inside a systemd-nspawn container. /usr/share/oem is mounted into this
   container as /mnt.

Customizing the image
<<<<<<<<<<<<<<<<<<<<<
There are several methods you can use to customize the IPA ramdisk:

* Embed SSH keys by putting an authorized_keys file in /usr/share/oem/
* Add your own hardware managers by modifying the Dockerfile to install
  additional python packages.
* Modify the cloud-config.yml [2]_ to perform additional tasks at boot time.

disk-image-builder
~~~~~~~~~~~~~~~~~~
There is currently no production-ready ironic-python-agent ramdisk images
using disk-image-builder, but one is currently under development [3]_.

ISO Images
~~~~~~~~~~
Additionally, the IPA ramdisk can be packaged inside of an ISO for use with
supported virtual media drivers. Simply use the ``iso-image-create`` utility
packaged with IPA, pass it an initrd and kernel. e.g.::

  ./iso-image-create -o /path/to/output.iso -i /path/to/ipa.initrd -k /path/to/ipa.kernel

This is a generic tool that can be used to combine any initrd and kernel into
a suitable ISO for booting, and so should work against any IPA ramdisk created
-- both DIB and CoreOS.

Hardware Managers
=================

What is a HardwareManager?
--------------------------
Hardware managers are how IPA supports multiple different hardware platforms
in the same agent. Any action performed on hardware can be overridden by
deploying your own hardware manager.

How are methods executed on HardwareManagers?
---------------------------------------------
Methods that modify hardware are dispatched to each hardware manager in
priority order. When a method is dispatched, if a hardware manager does not
have a method by that name or raises `IncompatibleHardwareMethodError`, IPA
continues on to the next hardware manager. Any hardware manager that returns
a result from the method call is considered a success and its return value
passed on to whatever dispatched the method. If the method is unable to run
successfully on any hardware managers, `HardwareManagerMethodNotFound` is
raised.

Does IPA ship with a HardwareManager?
-------------------------------------
IPA ships with GenericHardwareManager, which implements basic cleaning and
deployment methods compatible with most hardware.

Why build a custom HardwareManager?
-----------------------------------
Custom hardware managers allow you to include hardware-specific tools, files
and cleaning steps in the Ironic Python Agent. For example, you could include a
BIOS flashing utility and BIOS file in a custom ramdisk. Your custom
hardware manager could expose a cleaning step that calls the flashing utility
and flashes the packaged BIOS version (or even download it from a tested web
server).

How can I build a custom HardwareManager?
-----------------------------------------
Custom HardwareManagers should subclass hardware.HardwareManager or
hardware.GenericHardwareManager. The only required method is
evalutate_hardware_support(), which should return one of the enums
in hardware.HardwareSupport. Hardware support determines which hardware
manager is executed first for a given function (see: "`How are methods
executed on HardwareManagers?`_" for more info). Common methods you
may want to implement are list_hardware_info(), to add additional hardware
the GenericHardwareManager is unable to identify and erase_devices(), to
erase devices in ways other than ATA secure erase or shredding.

Versioning
~~~~~~~~~~
Each hardware manager has a name and a version. This version is used during
cleaning to ensure the same version of the agent is used to on a node through
the entire process. If the version changes, cleaning is restarted from the
beginning to ensure consistent cleaning operations and to make
updating the agent in production simpler.

You can set the version of your hardware manager by creating a class variable
named 'HARDWARE_MANAGER_VERSION', which should be a string. The default value
is '1.0'. You should change this version string any time you update your
hardware manager. You can also change the name your hardware manager presents
by creating a class variable called HARDWARE_MANAGER_NAME, which is a string.
The name defaults to the class name. Currently IPA only compares version as a
string; any version change whatsoever will enduce cleaning to restart.

Priority
~~~~~~~~
A hardware manager has a single overall priority, which should be based on how
well it supports a given piece of hardware. At load time, IPA executes
`evaluate_hardware_support()` on each method. This method should return an int
representing hardware manager priority, based on what it detects about the
platform its running on. Suggested values are included in the
`HardwareSupport` class. Returning a value of 0 aka `HardwareSupport.NONE`,
will prevent the hardware manager from being used. IPA will never ship a
hardware manager with a priority higher than 3, aka
`HardwareSupport.SERVICE_PROVIDER`.


Generated Developer Documentation
=================================

.. toctree::
   :maxdepth: 1

   api/autoindex


References
==========
.. [0] Enabling Drivers - http://docs.openstack.org/developer/ironic/deploy/drivers.html#ironic-python-agent-agent
.. [1] CoreOS PXE Images - https://coreos.com/docs/running-coreos/bare-metal/booting-with-pxe/
.. [2] CoreOS Cloud Init - https://coreos.com/docs/cluster-management/setup/cloudinit-cloud-config/
.. [3] DIB Element for IPA - https://github.com/openstack/diskimage-builder/tree/master/elements/ironic-agent

Indices and tables
==================

* :ref:`genindex`
* :ref:`modindex`
* :ref:`search`

