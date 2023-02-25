#!/usr/bin/python3

# native imports
import os
import re
import sys
import ast
import yaml
import time
import shutil
import logging
import datetime

# package index imports
import requests
import hashlib
import urllib.parse
import google.cloud.logging
from twilio.rest import Client
from pathlib import Path


# configure logging
if not os.environ.get("CLOUD_LOGGING"):
    logging.basicConfig(
        stream=sys.stdout,
        level=logging.INFO,
        format='%(asctime)s.%(msecs)03d (%(levelname)s | %(filename)s:%(lineno)d) - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    logging.info("Not logging to GCP, stdout selected instead")
else: google.cloud.logging.Client().setup_logging()


"""
Pulls daemon configuration from the local config.yml settings

Arguments:


Returns:


"""
def get_config(config_filename:str="config.yml"):
    # verify that config file exists, copy without readonly permission if not
    if not Path(f"./{config_filename}").is_file():
        shutil.copyfile("config-blank.yml", "config.yml")
        sys.exit("Configuration not found, created a template at ./config.yml")
    
    # open the file and read as yaml, validate yaml format via exception
    with open(config_filename, "rt") as fio:
        try:
            return yaml.safe_load(fio)
        except yaml.YAMLError as e:
            logging.error(e)


"""
Query the permitium site to see what timeslots are available in a given window

Arguments:
[0](int) start_time_epochms - the start of the window to search as epoch with ms
[1](int) end_time_epochms   - the end of the window to search as epoch with ms

Returns:
[0](list) - a list of available slots, no slots returns an empty list
"""
def get_timeslots(start_time_epochms:int, end_time_epochms:int) -> list:
    response = requests.get(
        url = f"https://sandiegoca.permitium.com/ccw/appointments"\
              f"?schedule=ccw_schedule&start={start_time_epochms}"\
              f"&end={end_time_epochms-1000}&permitType=ccw_new_permit")
    
    # ensure notification if the response fails
    if response.status_code != 200:
        logging.info(f"something went wrong: ({response.status_code}) {response.content}")
        return None

    # decode bytestring by ascii to a string literal list
    decoded_response = response.content.decode('ascii')

    # type-cast to a list via literal evaluation and return
    all_slots = ast.literal_eval(decoded_response)
    logging.info(f"checked for timeslots between {start_time_epochms} and {end_time_epochms}, found: {all_slots}")

    # check if there are new slots available else exit with none
    if all_slots:
        return min(all_slots)
    else:
        return None


def send_text_message(client: object,
                      sender_phone:str,
                      receiver_phone:str,
                      message_content:str) -> str:
    return client.messages.create(
        to=receiver_phone,
        from_=sender_phone,
        body=message_content
    ).sid

def reschedule(session_token:str, booking_time_ms:int):
    response = requests.post(
        url = f"https://sandiegoca.permitium.com/order_tracker_reschedule",
        data = f"newTime={booking_time_ms}"\
               "&newLocation=&newSchedule=ccw_schedule",
        headers = {"Content-Type": "application/x-www-form-urlencoded"},
        cookies = { "PLAY_SESSION": session_token }
    )


def get_session_token(order_number:str, email_address:str, password:str) -> str:
    response = requests.post(
        url = f"https://sandiegoca.permitium.com/order_tracker",
        data = f"orderid={order_number}"\
               f"&email={urllib.parse.quote(email_address)}"\
               f"&password={hashlib.sha256(password.encode('ascii')).hexdigest()}",
        headers = {"Content-Type": "application/x-www-form-urlencoded"},
    )

    # if we have a cookie we successfully authenticated, else there was a problem
    if 'Set-Cookie' in response.headers:
        # lots of parsing here to extract the actual cookie we want
        return response.headers['Set-Cookie'].split(';')[0].split('=')[1]
    else:
        logging.error(f"something went wrong with authentication: {response.headers}")
        sys.exit()

def get_current_booking(session_token:str) -> int:
    response = requests.get(
        url = "https://sandiegoca.permitium.com/order_tracker",
        cookies = { "PLAY_SESSION": session_token }
    )

    # parse the response from html
    extracted_html = re.search("(<u>).*(<\/u>)", response.content.decode('ascii')).group()
    extracted_timestamp = extracted_html.split('<')[1].split('>')[1]
    
    # parse the timestamp to epochms and return, from ie: February 12, 2024 1:00:00 PM PST
    return int(time.mktime(time.strptime(extracted_timestamp, "%B %d, %Y %I:%M:%S %p %Z"))*1000)


def watch_for_slots():
    # read the configuration out into a parsable object
    config = get_config()

    # create Twilio client
    twilio_client = Client(
        config['twilio']['account_sid'],
        config['twilio']['auth_token']
    )

    # get session token for initial check
    session_token = get_session_token(
            config["permitium"]["order_number"],
            config["permitium"]["email_address"],
            config["permitium"]["password"]
    )

    # get current session details for initial message
    current_booking_ms = get_current_booking(session_token)
    current_booking_dt = datetime.datetime.fromtimestamp(int(current_booking_ms/1000))
    current_time_ms = int(time.time()*1000)
    time_until_apt_s = int((current_booking_ms - current_time_ms)/1000)

    # send successful start message
    send_text_message(
        twilio_client,
        config['twilio']['sender_phone'],
        config['twilio']['receiver_phone'],
        f"The CCW interview watcher bot was successfully started. Your current interview date is {current_booking_dt} PST which is {datetime.timedelta(seconds = time_until_apt_s)} from now. You will be notified every time a better interview is found and booked. The bot will not book an interview closer than 30 hours from the current time."
    )

    # start checking for available slots
    while True:
        session_token = get_session_token(
            config["permitium"]["order_number"],
            config["permitium"]["email_address"],
            config["permitium"]["password"]
        )

        # get timing
        current_booking_ms = get_current_booking(session_token)
        current_booking_dt = datetime.datetime.fromtimestamp(int(current_booking_ms/1000))
        current_time_ms = int(time.time()*1000)
        time_until_apt_s = int((current_booking_ms - current_time_ms)/1000)
        logging.info(f"current booking ({current_booking_dt}) is"
              f" {datetime.timedelta(seconds = time_until_apt_s)} from now")

        # determine if there is a more preferable time
        best_timeslot_ms = get_timeslots(current_time_ms, current_booking_ms)
        if best_timeslot_ms:
            best_timeslot_dt = datetime.datetime.fromtimestamp(int(best_timeslot_ms/1000))

            # determine deltas
            delta_best_current_s = int((current_booking_ms - best_timeslot_ms)/1000)
            delta_best_current_dt = datetime.timedelta(seconds = delta_best_current_s)
            logging.info(f"found open booking at {best_timeslot_dt}, "
                        f"{delta_best_current_dt} sooner than the existing")

            # determine if there is a more preferable date (>30 hours out)
            if delta_best_current_s > 108000:
                logging.info(f"open booking is determined to be more desirable, rebooking")
                reschedule(session_token, best_timeslot_ms)

                logging.info(f"rebooked interview for {best_timeslot_dt} saving {delta_best_current_dt}")

                # send successful start message
                send_text_message(
                    twilio_client,
                    config['twilio']['sender_phone'],
                    config['twilio']['receiver_phone'],
                    f"Found and rebooked a closer interview on {best_timeslot_dt} PST saving {delta_best_current_dt}."
                )

        # sleep and continue
        time.sleep(config['general']['rate_of_check_seconds'])

if __name__ == "__main__":
    watch_for_slots()
