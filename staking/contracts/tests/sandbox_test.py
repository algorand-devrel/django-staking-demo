#!/usr/bin/env python

"""
Test script using sandbox.

Only for demonstration purposes.
"""

import os
import sys
import time
from datetime import datetime

import algosdk.future.transaction as txn
from algosdk import abi, logic
from algosdk.atomic_transaction_composer import (
    AtomicTransactionComposer,
    AccountTransactionSigner,
    TransactionWithSigner
)

from goal import Goal

stamp = datetime.now().strftime("%Y,%m/%d_%H:%M:%S")
print(f"{os.path.basename(sys.argv[0])} start {stamp}")

# Initialize to sandbox.
goal = Goal(
    name="unencrypted-default-wallet",
    algod_token=("a" * 64),
    algod_address="http://localhost:4001",
    kmd_token=("a" * 64),
    kmd_address="http://localhost:4002",
)

# App parameters
creator = goal.account
creator_sk = goal.sk
current_time = int(time.time())
begin_time = current_time + 25
end_time = begin_time + 325
fixed_rate = 1000 # 10%
print(f"UNIX time {current_time}")

staking_asset_id = 0
reward_asset_id = 0
app_id = 0

# ATC and helpers
atc = AtomicTransactionComposer()
creator_signer = AccountTransactionSigner(creator_sk)

# Create staking asset
staking_asset_total = 1_000_000_000_000_000
acfg = goal.acfg(
    creator,
    total=staking_asset_total,
    unit_name="SA",
    asset_name="Staking Asset",
)
txinfo, err = goal.send(acfg)
assert not err, err
staking_asset_id = txinfo["asset-index"]
assert goal.balance(creator, staking_asset_id) == staking_asset_total
print(f"Created staking asset: {staking_asset_id}")


# # Create reward asset
reward_asset_total = 1_000_000_000_000
acfg = goal.acfg(
    creator,
    total=reward_asset_total,
    unit_name="RA",
    asset_name="Reward Asset",
)
txinfo, err = goal.send(acfg)
assert not err, err
reward_asset_id = txinfo["asset-index"]
assert goal.balance(creator, reward_asset_id) == reward_asset_total
print(f"Created reward asset: {reward_asset_id}")

# Compile contract
teal = "pyteal_staking.teal"
clear_teal = "pyteal_clear.teal"
approval = goal.assemble(teal)
clear_prog = goal.assemble(clear_teal)

# Deploy new staking contract
# TODO: Move this to goal.py
deploy_method_args = [staking_asset_id, reward_asset_id, begin_time, end_time]
abi_deploy_method = abi.Method.from_signature("deploy(asset,asset,uint64,uint64)void")
atc.add_method_call(
    app_id=0,
    method=abi_deploy_method,
    sender=creator,
    sp=goal.get_sp(),
    signer=creator_signer,
    method_args=deploy_method_args,
    on_complete=txn.OnComplete.NoOpOC,
    local_schema=txn.StateSchema(3, 0),
    global_schema=txn.StateSchema(10, 1),
    approval_program=approval,
    clear_program=clear_prog,
    foreign_assets=[staking_asset_id, reward_asset_id],
)
deploy_results = atc.execute(goal.algod, 10)
txinfo = goal.confirm(deploy_results.tx_ids[0])
app_id = txinfo["application-index"]
assert app_id
print(f"APP ID {app_id}")

# Create minimum balance payment to staking contract
appl_addr = logic.get_application_address(app_id)
pay_minbal = goal.pay(goal.account, receiver=appl_addr, amt=302000)

# Initialize staking contract
atc = AtomicTransactionComposer()
atc.add_method_call(
    app_id=app_id,
    method=abi.Method.from_signature("init(pay,asset,asset)void"),
    sender=creator,
    sp=goal.get_sp(),
    signer=creator_signer,
    method_args=[TransactionWithSigner(pay_minbal, creator_signer), staking_asset_id, reward_asset_id],
    on_complete=txn.OnComplete.NoOpOC,
    foreign_assets=[staking_asset_id, reward_asset_id],
)
init_results = atc.execute(goal.algod, 10)
txinfo = goal.confirm(init_results.tx_ids[0])
print(f"Init tx: {txinfo}\n")

global_state = goal.app_read(app_id)
print(f"Global {global_state}\n")

# Transfer rewards to staking contract
atc = AtomicTransactionComposer()
reward_axfer = goal.axfer(creator, appl_addr, reward_asset_total, reward_asset_id)
atc.add_method_call(
    app_id=app_id,
    method=abi.Method.from_signature("reward(axfer,uint64,asset)void"),
    sender=creator,
    sp=goal.get_sp(),
    signer=creator_signer,
    method_args=[TransactionWithSigner(reward_axfer, creator_signer), fixed_rate, reward_asset_id],
    on_complete=txn.OnComplete.NoOpOC,
    foreign_assets=[staking_asset_id, reward_asset_id],
)
reward_results = atc.execute(goal.algod, 10)
txinfo = goal.confirm(reward_results.tx_ids[0])
print(f"reward tx: {txinfo}\n")

global_state = goal.app_read(app_id)
print(f"Global {global_state}\n")
