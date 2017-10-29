#!/usr/bin/env python

import uuid
import logging
import os
import re
import subprocess
import sys
import time

import logging

logging.basicConfig(level=logging.DEBUG)

def hrule():
    return "="*int(subprocess.check_output(["tput", "cols"]))

# A "snippet" is something that the user is supposed to do in the workshop.
# Most of the "snippets" are shell commands.
# Some of them can be key strokes or other actions.
# In the markdown source, they are the code sections (identified by triple-
# quotes) within .exercise[] sections.

class Snippet(object):

    def __init__(self, slide, content):
        self.slide = slide
        self.content = content
        self.actions = []

    def __str__(self):
        return self.content


class Slide(object):

    current_slide = 0

    def __init__(self, content):
        Slide.current_slide += 1
        self.number = Slide.current_slide

        # Remove commented-out slides
        # (remark.js considers ??? to be the separator for speaker notes)
        content = re.split("\n\?\?\?\n", content)[0]
        self.content = content

        self.snippets = []
        exercises = re.findall("\.exercise\[(.*)\]", content, re.DOTALL)
        for exercise in exercises:
            if "```" in exercise:
                for snippet in exercise.split("```")[1::2]:
                    self.snippets.append(Snippet(self, snippet))
            else:
                logging.warning("Exercise on slide {} does not have any ``` snippet."
                                .format(self.number))
                self.debug()

    def __str__(self):
        text = self.content
        for snippet in self.snippets:
            text = text.replace(snippet.content, ansi("7")(snippet.content))
        return text

    def debug(self):
        logging.debug("\n{}\n{}\n{}".format(hrule(), self.content, hrule()))


def ansi(code):
    return lambda s: "\x1b[{}m{}\x1b[0m".format(code, s)

def wait_for_success(wait_for=None):
    secs, timeout = 0, 30
    while secs <= timeout:
        time.sleep(1)
        output = subprocess.check_output(["tmux", "capture-pane", "-p"])
        if wait_for and wait_for in output:
            return True
        # If there's a prompt at the end, the command completed
        if output[-3:-1] == "\n$":
            ec = check_exit_code()
            return True if ec == 0 else ec
        else:
            print(".")
        secs += 1

def check_exit_code():
    token = uuid.uuid4().hex
    data = "echo {} $?\n".format(token)
    subprocess.check_call(["tmux", "send-keys", "{}".format(data)])
    time.sleep(0.5)
    screen = subprocess.check_output(["tmux", "capture-pane", "-p"])
    output = [x for x in screen.split("\n") if x]
              #if x.startswith(token)]
    ec = [x for x in output if x.startswith(token)]
    if not ec:
        raise Exception("Couldn't retrieve exit code")
    ret = int(ec[0].split()[1])
    return ret

slides = []
content = open(sys.argv[1]).read()
for slide in re.split("\n---?\n", content):
    slides.append(Slide(slide))

actions = []
for slide in slides:
    for snippet in slide.snippets:
        content = snippet.content
        # Extract the "method" (e.g. bash, keys, ...)
        # On multi-line snippets, the method is alone on the first line
        # On single-line snippets, the data follows the method immediately
        if '\n' in content:
            method, data = content.split('\n', 1)
        else:
            method, data = content.split(' ', 1)
        actions.append((slide, snippet, method, data))


try:
    i = int(open("nextstep").read())
    logging.info("Loaded next step ({}) from file.".format(i))
except Exception as e:
    logging.warning("Could not read nextstep file ({}), initializing to 0.".format(e))
    i = 0


keymaps = { "^C": "\x03" }

wait_for, stop_action, method = "", "", ""

interactive = True
if os.environ.get("WORKSHOP_TEST_FORCE_NONINTERACTIVE"):
    interactive=False

while i < len(actions):
    with open("nextstep","w") as f:
        f.write(str(i))
    slide, snippet, method, data = actions[i]
    data = data.strip()

    # Look behind at the last slide to see if 'wait' or 'keys' was defined.
    # If so, we need to wait for the specified output and/or terminate the command with the specified keys.
    if method == "wait":
        wait_for = data
        logging.info("Setting wait_for to: {}".format(data))
        i += 1
        continue
    if method == "keys":
        stop_action = data
        logging.info("Setting stop_action to: {}".format(data))
        i += 1
        continue
    print(hrule())
    print(slide.content.replace(snippet.content, ansi(7)(snippet.content)))
    print(hrule())
    if wait_for:
        logging.info("waiting for: {}".format(wait_for))
    if stop_action:
        logging.info("stop_action: {}".format(stop_action))
    command = ""
    if interactive:
        command = raw_input("[{}] Shall we execute that snippet above? ('c' to continue without further prompting) ".format(i))
    logging.info("Running: {}".format(data))
    if command == "c":
        # continue until next timeout
        interactive = False
    if command == "":
        if method=="keys" and data in keymaps:
            print("Mapping {!r} to {!r}.".format(data, keymaps[data]))
            data = keymaps[data]
        if method in ["bash", "keys"]:
            data = re.sub("\n +", "\n", data)
            if method == "bash":
                data += "\n"
            subprocess.check_call(["tmux", "send-keys", "{}".format(data)])
            result = wait_for_success(wait_for=wait_for)
            if result is True:
                if stop_action:
                    subprocess.check_call(["tmux", "send-keys", "{}".format(stop_action)])
                    wait_for_success()
                # Unset wait_for and stop_action so they don't carry over to the next loop.
                wait_for, stop_action = "", ""
            elif type(result) == type(0):
                logging.warning("Last command failed (exit code {})!".format(result))
                if os.environ.get("WORKSHOP_TEST_FORCE_NONINTERACTIVE"):
                    raise Exception("Command failed (exit code): {} ({})".format(data, result))
                interactive = True
            else:
                logging.warning("Last command timed out!")
                if os.environ.get("WORKSHOP_TEST_FORCE_NONINTERACTIVE"):
                    raise Exception("Command timed out: {}".format(data))
                interactive = True
        else:
            logging.warning("DO NOT KNOW HOW TO HANDLE {} {!r}".format(method, data))
        i += 1
    elif command.isdigit():
        i = int(command)
    else:
        i += 1
        # skip other "commands"

# Reset slide counter
with open("nextstep", "w") as f:
    f.write(str(0))
