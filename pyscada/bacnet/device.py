# -*- coding: utf-8 -*-
from __future__ import unicode_literals

import pyscada

try:
    driver_ok = True
except ImportError:
    driver_ok = False

from math import isnan, isinf
from time import time
import sys
import traceback

from bacpypes.consolelogging import ConfigArgumentParser

from bacpypes.core import run, stop, enable_sleeping

from bacpypes.pdu import Address, GlobalBroadcast
from bacpypes.apdu import WhoIsRequest, IAmRequest, SimpleAckPDU, Error
from bacpypes.apdu import ReadPropertyMultipleRequest, PropertyReference
from bacpypes.apdu import ReadAccessSpecification, ReadPropertyMultipleACK, SubscribeCOVRequest
from bacpypes.primitivedata import Unsigned
from bacpypes.constructeddata import Array
from bacpypes.errors import DecodingError
from bacpypes.primitivedata import CharacterString
from bacpypes.object import get_object_class, get_datatype

from bacpypes.app import BIPSimpleApplication
from bacpypes.local.device import LocalDeviceObject
from bacpypes.basetypes import ServicesSupported, DeviceStatus, PropertyIdentifier
from bacpypes.iocb import IOCB
from bacpypes.errors import ExecutionError


from threading import Thread
import random

import BAC0

from pyscada.utils.scheduler import SingleDeviceDAQProcess
from pyscada.models import Variable

import logging

logger = logging.getLogger(__name__)
_debug = 1


class Server:
    """
    BACnet Server that implements all communication over IP
    """
    def __init__(self, local_ip, local_object_name='PyScada', device_id=None,
                 max_APDU_length_accepted='1024', max_segments_accepted='1024',
                 segmentation_supported='segmentedBoth',
                 bbmd_address=None, bbmd_TTL=0, *args):

        if _debug: logger.debug("__init__ %r", args)
        self.this_device = None
        self.this_application = None

        self.local_ip = local_ip
        self.local_object_name = local_object_name
        self.boid = int(device_id) if device_id else (3056177 + int(random.uniform(0, 1000)))
        self.vendor_id = 0
        self.vendor_name = CharacterString('PyScada')
        self.model_name = CharacterString('BACnet DAQ Service')
        self.system_status = DeviceStatus(1)
        self.max_APDU_length_accepted = max_APDU_length_accepted
        self.max_segments_accepted = max_segments_accepted
        self.segmentation_supported = segmentation_supported
        self.bbmd_address = bbmd_address
        self.bbmd_TTL = bbmd_TTL
        self.t = None

    def connect(self):
        """

        :return:
        """
        try:
            self.this_device = LocalDeviceObject(
                objectName=self.local_object_name,
                objectIdentifier=self.boid,
                maxApduLengthAccepted=int(self.max_APDU_length_accepted),
                segmentationSupported=self.segmentation_supported,
                vendorIdentifier=self.vendor_id,
                vendorName=self.vendor_name,
                modelName=self.model_name,
                systemStatus=self.system_status,
                description='PyScada BACnet DAQs Service (https://github.com/pyscada/pyscada)',
                firmwareRevision=''.join(sys.version.split('|')[:2]),
                applicationSoftwareVersion=pyscada.core.version(),
                protocolVersion=1,
                protocolRevision=0,
            )
            self.this_application = BIPApplication(
                self.this_device, self.local_ip)
            app_type = 'Simple BACnet/IP App'

            logger.debug("Starting")
            try:
                logger.info('Starting app...')
                enable_sleeping(0.0005)
                self.t = Thread(target=run, kwargs={
                    'sigterm': None, 'sigusr1': None}, daemon=True)
                self.t.start()
                logger.info('BAC0 started')
                print("Registered as {}".format(app_type))
            except:
                logger.warning("Error opening socket")
                raise
            logger.debug("Running")

        except Exception as error:
            logger.error("an error has occurred: {}".format(error))
            logger.error('%s unhandled exception\n%s' % (self, traceback.format_exc()))
        finally:
            logger.debug("finally")

    def disconnect(self):
        """
        Stop the BACnet stack.  Free the IP socket.
        """
        print('Stopping BACnet stack')
        # Freeing socket
        try:
            self.this_application.mux.directPort.handle_close()
        except:
            self.this_application.mux.broadcastPort.handle_close()

        stop()                  # Stop Core
        self.t.join()
        logger.info('BACnet stopped')


class BIPApplication(BIPSimpleApplication):

    def __init__(self, *args):
        if _debug: logger.debug("__init__ %r", args)
        try:
            BIPSimpleApplication.__init__(self, *args)
        except OSError as e:
            logger.error("BACnet error : %s" % str(e))

        # keep track of requests to line up responses
        self._request = None

    def do_whois(self, addr=None, lolimit=None, hilimit=None):
        """whois [ <addr>] [ <lolimit> <hilimit> ]"""

        try:
            # build a request
            request = WhoIsRequest()
            if (addr is None):
                request.pduDestination = GlobalBroadcast()
            else:
                request.pduDestination = Address(addr)

            if lolimit is not None:
                request.deviceInstanceRangeLowLimit = int(lolimit)
            if hilimit is not None:
                request.deviceInstanceRangeHighLimit = int(hilimit)
            if _debug: logger.debug("    - request: %r", request)

            # make an IOCB
            iocb = IOCB(request)
            if _debug: logger.debug("    - iocb: %r", iocb)

            # give it to the application
            self.request_io(iocb)

        except Exception as err:
            logger.debug("exception: %r", err)

    def do_iam(self):
        """iam"""
        try:
            # build a request
            request = IAmRequest()
            request.pduDestination = GlobalBroadcast()

            # set the parameters from the device object
            request.iAmDeviceIdentifier = this_device.objectIdentifier
            request.maxAPDULengthAccepted = this_device.maxApduLengthAccepted
            request.segmentationSupported = this_device.segmentationSupported
            request.vendorID = this_device.vendorIdentifier
            if _debug: logger.debug("    - request: %r", request)

            # make an IOCB
            iocb = IOCB(request)
            if _debug: logger.debug("    - iocb: %r", iocb)

            # give it to the application
            self.request_io(iocb)

        except Exception as err:
            logger.debug("exception: %r", err)

    def do_read(self, addr, properties):
        """read <addr> ( <type> <inst> ( <prop> [ <indx> ] )... )..."""
        read_access_spec_list = []
        try:
            for obj_type, obj_inst, props in properties:
                if type(obj_type) is int:
                    pass
                elif obj_type.isdigit():
                    obj_type = int(obj_type)
                elif not get_object_class(obj_type):
                    raise ValueError("unknown object type")

                prop_reference_list = []
                for prop_id, idx in props:
                    if prop_id not in PropertyIdentifier.enumerations:
                        break

                    if prop_id in ('all', 'required', 'optional'):
                        pass
                    else:
                        logger.debug(obj_type)
                        logger.debug(prop_id)
                        datatype = get_datatype(obj_type, prop_id)
                        if not datatype:
                            raise ValueError("invalid property for object type")

                    # build a property reference
                    prop_reference = PropertyReference(
                        propertyIdentifier=prop_id,
                    )

                    # check for an array index
                    if idx is not None:
                        prop_reference.propertyArrayIndex = int(idx)

                    # add it to the list
                    prop_reference_list.append(prop_reference)

                # check for at least one property
                if not prop_reference_list:
                    raise ValueError("provide at least one property")
                # build a read access specification
                read_access_spec = ReadAccessSpecification(
                    objectIdentifier=(obj_type, obj_inst),
                    listOfPropertyReferences=prop_reference_list,
                )
                # add it to the list
                read_access_spec_list.append(read_access_spec)

            # check for at least one
            if not read_access_spec_list:
                raise RuntimeError("at least one read access specification required")

            # build the request
            request = ReadPropertyMultipleRequest(
                listOfReadAccessSpecs=read_access_spec_list,
            )
            request.pduDestination = Address(addr)
            if _debug: logger.debug("    - request: %r", request)
            self._request = request
            # make an IOCB
            iocb = IOCB(request)
            if _debug: logger.debug("    - iocb: %r", iocb)

            # give it to the application
            self.request_io(iocb)

            logger.debug(iocb.ioComplete.is_set())

            # do something for error/reject/abort
            if iocb.ioError:
                logger.error(str(iocb.ioError))

            try:
                return float(iocb.ioResponse)
            except:
                logger.error("Data not a number : %s" % iocb.ioResponse)
                return None

        except Exception as error:
            logger.debug("exception: %r", error)
            logger.error('%s unhandled exception\n%s' % (self, traceback.format_exc()))

    def send_subscription(self, addr, proc_id, objid, confirmed=None, lifetime=None):
        if _debug: logger.debug("send_subscription")

        # build a request
        request = SubscribeCOVRequest(
            subscriberProcessIdentifier= proc_id,
            monitoredObjectIdentifier= objid,
            )
        request.pduDestination = Address(addr)

        # optional parameters
        if confirmed is not None:
            request.issueConfirmedNotifications = confirmed
        if lifetime is not None:
            request.lifetime = lifetime

        self._request = request

        # make an IOCB
        iocb = IOCB(request)
        if _debug: logger.debug("    - iocb: %r", iocb)

        # callback when it is acknowledged
        #iocb.add_callback(self.subscription_acknowledged)

        # give it to the application
        self.request_io(iocb)

    def request(self, apdu):
        if _debug: logger.debug("request %r", apdu)

        # save a copy of the request
        self._request = apdu

        # forward it along
        BIPSimpleApplication.request(self, apdu)

    def subscription_acknowledged(self, iocb):
        if _debug: logger.debug("subscription_acknowledged %r", iocb)

        # do something for success
        if iocb.ioResponse:
            if _debug: logger.debug("    - response: %r", iocb.ioResponse)

        # do something for error/reject/abort
        if iocb.ioError:
            if _debug: logger.debug("    - error: %r", iocb.ioError)

    def confirmation(self, apdu):
        if _debug: logger.debug("confirmation %r", apdu)

        if isinstance(self._request, ReadPropertyMultipleRequest) and isinstance(apdu, ReadPropertyMultipleACK):
            if _debug: logger.debug("handle ReadPropertyMultipleRequest - ReadPropertyMultipleACK")
            self.confirmation__read_property_multiple_ack(apdu)
            self._request = None
        elif isinstance(self._request, SubscribeCOVRequest) and isinstance(apdu, SimpleAckPDU):
            if _debug: logger.debug("handle SubscribeCOVRequest - SimpleAckPDU")
            self._request = None
        elif isinstance(apdu, Error): # handle Error Response
            if _debug: logger.debug("handle * - Error")
            self._request = None

        # forward it along
        BIPSimpleApplication.confirmation(self, apdu)

    def indication(self, apdu):
        if _debug: logger.debug("indication %r", apdu)

        if (isinstance(self._request, WhoIsRequest)) and (isinstance(apdu, IAmRequest)): # WhoIsRequest - IAmRequest
            if _debug: logger.debug("handle WhoIsRequest - IAmRequest")
            device_type, device_instance = apdu.iAmDeviceIdentifier
            if device_type != 'device':
                raise DecodingError("invalid object type")

            if (self._request.deviceInstanceRangeLowLimit is not None) and \
                    (device_instance < self._request.deviceInstanceRangeLowLimit):
                pass
            elif (self._request.deviceInstanceRangeHighLimit is not None) and \
                    (device_instance > self._request.deviceInstanceRangeHighLimit):
                pass
            else:
                # print out the contents
                logger.debug('pduSource = ' + repr(apdu.pduSource) + '\n')
                logger.debug('iAmDeviceIdentifier = ' + str(apdu.iAmDeviceIdentifier) + '\n')
                logger.debug('maxAPDULengthAccepted = ' + str(apdu.maxAPDULengthAccepted) + '\n')
                logger.debug('segmentationSupported = ' + str(apdu.segmentationSupported) + '\n')
                logger.debuge('vendorID = ' + str(apdu.vendorID) + '\n')
            self._request = None
        # forward it along
        BIPSimpleApplication.indication(self, apdu)

    def confirmation__read_property_multiple_ack(self, apdu):
        # loop through the results
        for result in apdu.listOfReadAccessResults:
            # here is the object identifier
            objectIdentifier = result.objectIdentifier
            if _debug: logger.debug("    - objectIdentifier: %r", objectIdentifier)

            # now come the property values per object
            for element in result.listOfResults:
                # get the property and array index
                propertyIdentifier = element.propertyIdentifier
                if _debug: logger.debug("    - propertyIdentifier: %r",
                                        propertyIdentifier)
                propertyArrayIndex = element.propertyArrayIndex
                if _debug: logger.debug("    - propertyArrayIndex: %r",
                                        propertyArrayIndex)

                # here is the read result
                readResult = element.readResult

                logger.debug(str(propertyIdentifier))
                if propertyArrayIndex is not None:
                    logger.debug("[" + str(propertyArrayIndex) + "]")

                # check for an error
                if readResult.propertyAccessError is not None:
                    logger.debug(" ! " + str(readResult.propertyAccessError))

                else:
                    # here is the value
                    propertyValue = readResult.propertyValue

                    # find the datatype
                    datatype = get_datatype(objectIdentifier[0], propertyIdentifier)
                    if _debug: logger.debug("    - datatype: %r", datatype)
                    if not datatype:
                        value = '?'
                    else:
                        # special case for array parts, others are managed by cast_out
                        if issubclass(datatype, Array) and (propertyArrayIndex is not None):
                            if propertyArrayIndex == 0:
                                value = propertyValue.cast_out(Unsigned)
                            else:
                                value = propertyValue.cast_out(datatype.subtype)
                        else:
                            value = propertyValue.cast_out(datatype)
                        if _debug: logger.debug("    - value: %r", value)

                    logger.debug(" = " + str(value))


class Device:
    """
    BACNet device (Master)
    """

    def __init__(self, device):
        self.device = device
        self._device_not_accessible = 0

        self.server = BAC0.lite(ip=str(self.device.bacnetdevice.ip_address) + "/" + str(self.device.bacnetdevice.mask),
                                port=self.device.bacnetdevice.port)

        self.remote_devices = {}
        self.variables = {}
        self.data = []

        #if not self._connect():
        #    if self._device_not_accessible == -1:  #
        #        logger.error("device with id: %d is not accessible" % self.device.pk)
        #    self._device_not_accessible -= 1

        for dev in self.device.bacnet_remote_devices.filter(bacnet_device__active=1):
            self.remote_devices[dev.bacnet_device.pk] = dev.bacnet_device

            for var in dev.bacnet_device.variable_set.filter(active=1):
                if not hasattr(var, 'bacnetvariable'):
                    continue
                self.variables[var.pk] = var

    def _connect(self):
        """
        connect to the bacnet slave (server)
        """
        status = self.server.connect()
        return status

    def _disconnect(self):
        """
        disconnect to the bacnet slave (server)
        """
        logger.debug("Disconnecting BACNet device")
        status = self.server.disconnect()
        return status

    def request_data(self):
        """

        """
        if not driver_ok:
            return None

        output = []
        properties = []

        for item in self.variables.values():
            try:
                value = float(self.server.read(str(item.device.bacnetdevice.ip_address)
                                               + " "
                                               + str(item.bacnetvariable.object_type_choises[item.bacnetvariable.object_type][1])
                                               + " "
                                               + str(item.bacnetvariable.object_identifier)
                                               + " "
                                               + "presentValue"))
            except BAC0.core.io.IOExceptions.NoResponseFromController as e:
                logger.info("%s : %s" % (self.device, e))
                value = None
            except ValueError:
                if type(value) == str:
                    value = item.convert_string_value(value)
                else:
                    logger.info("Value read for %s format not supported : %s" % (item, type(value)))
                    value = None
            except Exception as e:
                logger.info("%s : %s" % (self.device, e))
                value = None
            if value is not None and item.update_value(value, time()):
                output.append(item.create_recorded_data_element())
            #properties.append([item.bacnetvariable.object_type_choises[item.bacnetvariable.object_type][1], item.bacnetvariable.object_identifier, [('presentValue', 0)]])

        #if self.server.this_application is not None:
        #    logger.debug(self.server.this_application.do_read(self.device.bacnetdevice.ip_address, properties))



        #for item in self.variables.values():
        #    if value is not None and item.update_value(value, time):
        #        output.append(item.create_recorded_data_element())
        return output

    def write_data(self, variable_id, value, task):
        """

        """
        logger.debug(variable_id)
        logger.debug(value)
        logger.debug(task)
        if not driver_ok:
            return None

        output = []
        properties = []

        v = Variable.objects.get(id=variable_id)
        if v is None:
            return output
        elif not v.writeable:
            logger.debug("%s is not writeable" % v)

        try:
            value = float(self.server.write(str(v.device.bacnetdevice.ip_address)
                                            + " "
                                            + str(v.bacnetvariable.object_type_choises[v.bacnetvariable.object_type][1])
                                            + " "
                                            + str(v.bacnetvariable.object_identifier)
                                            + " "
                                            + "presentValue "
                                            + value
                                            + " - 1"))
        except BAC0.core.io.IOExceptions.NoResponseFromController as e:
            logger.info("%s : %s" % (self.device, e))
            value = None
        except Exception as e:
            logger.info("%s : %s" % (self.device, e))
            value = None
        if value is not None and v.update_value(value, time()):
            output.append(v.create_recorded_data_element())

        return output


class Process(SingleDeviceDAQProcess):
    device_filter = dict(bacnetdevice__isnull=False)
    bp_label = 'pyscada.bacnet-%s'

    def restart(self):
        """
        just re-init
        """
        self.device._disconnect()
        if self.device.device.bacnetdevice.device_type == 0:
            return super(Process, self).restart()
        else:
            logger.debug("Not a local bacnet device : not restarting")
            self.stop()
