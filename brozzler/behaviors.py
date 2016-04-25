#
# brozzler/behaviors.py - manages behaviors, which are javascript scripts that
# run in brozzled web pages
#
# Copyright (C) 2014-2016 Internet Archive
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#

import json
import itertools
import os
import re
import logging
import time
import sys
import yaml
import string

__all__ = ["Behavior"]

class Behavior:
    logger = logging.getLogger(__module__ + "." + __qualname__)

    _behaviors = None

    @staticmethod
    def behaviors():
        if Behavior._behaviors is None:
            behaviors_yaml = os.path.sep.join(__file__.split(os.path.sep)[:-1] + ['behaviors.yaml'])
            with open(behaviors_yaml) as fin:
                conf = yaml.load(fin)
            Behavior._behaviors = conf['behaviors']

            simpleclicks_js_in = os.path.sep.join(__file__.split(os.path.sep)[:-1] + ["behaviors.d"] + ["simpleclicks.js.in"])
            with open(simpleclicks_js_in) as fin:
                simpleclicks_js_template = string.Template(fin.read())

            for behavior in Behavior._behaviors:
                if "behavior_js" in behavior:
                    behavior_js = os.path.sep.join(__file__.split(os.path.sep)[:-1] + ["behaviors.d"] + [behavior["behavior_js"]])
                    behavior["script"] = open(behavior_js, encoding="utf-8").read()
                elif "click_css_selector" in behavior:
                    if "click_until_hard_timeout" in behavior: 
                        click_until_hard_timeout_value=behavior["click_until_hard_timeout"]
                    else:
                        click_until_hard_timeout_value = False
                    behavior["script"] = simpleclicks_js_template.substitute(click_css_selector=behavior["click_css_selector"], click_until_hard_timeout=click_until_hard_timeout_value)

        return Behavior._behaviors

    def __init__(self, url, umbra_worker):
        self.url = url
        self.umbra_worker = umbra_worker

        self.script_finished = False
        self.waiting_result_msg_ids = []
        self.active_behavior = None
        self.last_activity = time.time()

    def start(self):
        for behavior in Behavior.behaviors():
            if re.match(behavior['url_regex'], self.url):
                if "behavior_js" in behavior:
                    self.logger.info("using {} behavior for {}".format(behavior["behavior_js"], self.url))
                elif "click_css_selector" in behavior:
                    self.logger.info("using simple click behavior with css selector {} for {}".format(behavior["click_css_selector"], self.url))

                self.active_behavior = behavior
                self.umbra_worker.send_to_chrome(method="Runtime.evaluate",
                        suppress_logging=True, params={"expression": behavior["script"]})
                self.notify_of_activity()
                return

        self.logger.warn("no behavior to run on {}".format(self.url))

    def is_finished(self):
        """Asynchronously asks behavior if it is finished, and in the mean time
        returns the response from the previous such query."""
        msg_id = self.umbra_worker.send_to_chrome(method="Runtime.evaluate",
                suppress_logging=True, params={"expression":"umbraBehaviorFinished()"})
        self.waiting_result_msg_ids.append(msg_id)

        request_idle_timeout_sec = 30
        if self.active_behavior and 'request_idle_timeout_sec' in self.active_behavior:
            request_idle_timeout_sec = self.active_behavior['request_idle_timeout_sec']
        idle_time = time.time() - self.last_activity

        return self.script_finished and idle_time > request_idle_timeout_sec

    def is_waiting_on_result(self, msg_id):
        return msg_id in self.waiting_result_msg_ids

    def notify_of_result(self, chrome_message):
        # {'id': 59, 'result': {'result': {'type': 'boolean', 'value': True}, 'wasThrown': False}}
        # {'id': 59, 'result': {'result': {'type': 'boolean', 'value': False}}
        self.waiting_result_msg_ids.remove(chrome_message['id'])
        if ('result' in chrome_message
                and not ('wasThrown' in chrome_message['result'] and chrome_message['result']['wasThrown'])
                and 'result' in chrome_message['result']
                and type(chrome_message['result']['result']['value']) == bool):
            self.script_finished = chrome_message['result']['result']['value']
        else:
            self.logger.error("chrome message doesn't look like a boolean result! {}".format(chrome_message))

    def notify_of_activity(self):
        self.last_activity = time.time()

if __name__ == "__main__":
    logging.basicConfig(stream=sys.stdout, level=logging.DEBUG,
            format='%(asctime)s %(process)d %(levelname)s %(threadName)s %(name)s.%(funcName)s(%(filename)s:%(lineno)d) %(message)s')
    logger = logging.getLogger('umbra.behaviors')
    logger.info("custom behaviors: {}".format(Behavior.behaviors()))


