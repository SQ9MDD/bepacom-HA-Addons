"""Main script for EcoPanel BACnet add-on."""

import asyncio
import configparser
import json
import logging
from typing import TypeVar

import uvicorn
import webAPI
from BACnetIOHandler import BACnetIOHandler
from bacpypes3.argparse import INIArgumentParser
from bacpypes3.basetypes import Segmentation
from bacpypes3.ipv4.app import Application
from bacpypes3.local.device import DeviceObject
from bacpypes3.pdu import Address, IPv4Address
from bacpypes3.primitivedata import ObjectIdentifier
from webAPI import app as fastapi_app

KeyType = TypeVar("KeyType")


def exception_handler(loop, context):
    """Handle uncaught exceptions"""
    try:
        logging.error(f'An error occurred: {context["exception"]}')
    except:
        logging.error("Tried to log error, but something went horribly wrong!!!")


async def updater_task(app: Application, interval: int, event: asyncio.Event) -> None:
    """Task to handle periodic updates to the BACnet dictionary"""
    try:
        while True:
            try:
                await asyncio.wait_for(event.wait(), timeout=interval)
                event.clear()
            except asyncio.TimeoutError:
                await app.read_objects_periodically()

    except asyncio.CancelledError as err:
        logging.warning(f"Updater task cancelled: {err}")


async def writer_task(app: Application, write_queue: asyncio.Queue) -> None:
    """Task to handle the write queue"""
    try:
        global default_write_prio
        while True:
            queue_result = await write_queue.get()
            device_id = queue_result[0]
            object_id = queue_result[1]
            property_id = queue_result[2]
            property_val = queue_result[3]
            array_index = queue_result[4]
            priority = queue_result[5]

            if queue_result[5] is None:
                queue_result[5] = default_write_prio
            await app.write_property(
                address=app.dev_to_addr(device_id),
                objid=object_id,
                prop=property_id,
                value=property_val,
                array_index=array_index,
                priority=priority,
            )
            read = await app.read_property(
                address=app.dev_to_addr(device_id),
                objid=object_id,
                prop=property_id,
                array_index=array_index,
            )
            logging.info(f"Write result: {read}")

            app.dict_updater(
                device_identifier=device_id,
                object_identifier=object_id,
                property_identifier=property_id,
                property_value=property_val,
            )

    except Exception as err:
        logging.error(f" Writer task error: {err}")
    except asyncio.CancelledError as err:
        logging.warning(f"Writer task cancelled: {err}")


async def subscribe_handler_task(app: Application, sub_queue: asyncio.Queue) -> None:
    """Task to handle the subscribe queue"""
    try:
        while True:
            queue_result = await sub_queue.get()
            device_identifier = queue_result[0]
            object_identifier = queue_result[1]
            notifications = queue_result[2]
            lifetime = queue_result[3]

            for task in app.subscription_tasks:
                if task[1] == object_identifier and task[4] == device_identifier:
                    logging.error(
                        f"Subscription for {device_identifier}, {object_identifier} already exists"
                    )
                    break
            else:
                await app.create_subscription_task(
                    device_identifier=device_identifier,
                    object_identifier=object_identifier,
                    confirmed_notifications=notifications,
                    lifetime=lifetime,
                )

    except asyncio.CancelledError as err:
        logging.warning(f"Subscribe task cancelled: {err}")


async def unsubscribe_handler_task(
    app: Application, unsub_queue: asyncio.Queue
) -> None:
    """Task to handle the unsubscribe queue"""
    try:
        while True:
            queue_result = await unsub_queue.get()
            device_identifier = queue_result[0]
            object_identifier = queue_result[1]

            for task in app.subscription_tasks:
                if task[1] == object_identifier and task[4] == device_identifier:
                    await app.unsubscribe_COV(
                        subscriber_process_identifier=task[0],
                        device_identifier=task[4],
                        object_identifier=task[1],
                    )
                    break
            else:
                logging.error(
                    f"Subscription task '{device_identifier}, {object_identifier}' does not exist"
                )

    except asyncio.CancelledError as err:
        logging.warning(f"Unsubscribe task cancelled: {err}")


async def main():
    """Main function of the application."""

    loop = asyncio.get_event_loop()

    loop.set_exception_handler(exception_handler)

    config = configparser.ConfigParser()

    config.read("/usr/bin/BACpypes.ini")

    global default_write_prio

    default_write_prio = config.get("BACpypes", "defaultPriority")

    loglevel = config.get("BACpypes", "loglevel")

    logging.basicConfig(format="%(levelname)s:    %(message)s", level=loglevel)

    ipv4_address = IPv4Address(config.get("BACpypes", "address"))

    this_device = DeviceObject(
        objectIdentifier=ObjectIdentifier(
            f"device,{config.get('BACpypes', 'objectIdentifier')}"
        ),
        objectName=config.get("BACpypes", "objectName"),
        description="BACnet Add-on for Home Assistant",
        vendorIdentifier=int(config.get("BACpypes", "vendorIdentifier")),
        segmentationSupported=Segmentation(config.get("BACpypes", "segmentation")),
        maxApduLengthAccepted=int(config.get("BACpypes", "maxApduLengthAccepted")),
        maxSegmentsAccepted=int(config.get("BACpypes", "maxSegmentsAccepted")),
    )

    app = BACnetIOHandler(this_device, ipv4_address)

    app.asap.maxApduLengthAccepted = int(
        config.get("BACpypes", "maxApduLengthAccepted")
    )

    app.asap.segmentationSupported = Segmentation(
        config.get("BACpypes", "segmentation")
    )

    app.asap.maxSegmentsAccepted = int(config.get("BACpypes", "maxSegmentsAccepted"))

    update_task = asyncio.create_task(
        updater_task(
            app=app,
            interval=int(config.get("BACpypes", "updateInterval")),
            event=webAPI.events.read_event,
        )
    )

    write_task = asyncio.create_task(
        writer_task(app=app, write_queue=webAPI.events.write_queue)
    )

    sub_task = asyncio.create_task(
        subscribe_handler_task(app=app, sub_queue=webAPI.events.sub_queue)
    )

    unsub_task = asyncio.create_task(
        unsubscribe_handler_task(app=app, unsub_queue=webAPI.events.unsub_queue)
    )

    webAPI.sub_list = app.subscription_tasks
    webAPI.bacnet_device_dict = app.bacnet_device_dict
    webAPI.who_is_func = app.who_is
    webAPI.i_am_func = app.i_am
    webAPI.events.val_updated_event = app.update_event
    webAPI.events.startup_complete_event = app.startup_complete

    if loglevel == "DEBUG":
        uvilog = "info"
    else:
        uvilog = loglevel.lower()

    config = uvicorn.Config(
        app=fastapi_app, host="127.0.0.1", port=7813, log_level=uvilog
    )

    server = uvicorn.Server(config)

    await server.serve()

    if app:
        update_task.cancel()
        write_task.cancel()
        sub_task.cancel()
        unsub_task.cancel()
        await app.end_subscription_tasks()
        app.close()


if __name__ == "__main__":
    asyncio.run(main())