#!/usr/bin/python3

# native imports
import os
import sys
import ast
import yaml
import shutil
import logging

# package index imports
import requests
import google.cloud.logging
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
def get_config(config_filename:str):
    # verify that config file exists, copy without readonly permission if not
    if not Path(f"./{config_filename}").is_file():
        shutil.copyfile(".config-blank.yml", "config.yml")
        sys.exit("Configuration not found, created a template at ./config.yml")
    
    # open the file and read as yaml, validate yaml format via exception
    with open("./config.yml", "rt") as fio:
        try:
            print(yaml.safe_load(fio))
        except yaml.YAMLError as e:
            print(e)

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
              f"&end={end_time_epochms}&permitType=ccw_new_permit")

    # decode bytestring by ascii to a string literal list
    decoded_response = response.content.decode('ascii')

    # type-cast to a list via literal evaluation and return
    return ast.literal_eval(decoded_response)


def send_textmessage():
    pass

def attempt_reschedule():
    pass



if __name__ == "__main__":
    print(get_timeslots(1677278487000, 1708814487000))
    #check_timeslots(1708814487000, 1708814487000)