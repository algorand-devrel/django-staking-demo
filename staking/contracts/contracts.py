#!/usr/bin/env python3

import json
from pyteal import (pragma, Seq, Subroutine, TealType, Expr, abi, Router, BareCallActions, OnCompleteAction, Approve, CallConfig, Assert, TxnType, Txn, Global, App, Bytes, Not, If, Return, ScratchVar, Int, OnComplete, Reject, InnerTxnBuilder, TxnField, Gt, Ge, Balance, For)

pragma(compiler_version="^0.18.1")

# Constants
CONTRACT_VERSION = 6
ADMIN_ADDRESS = Bytes("A")
INIT_FLAG = Bytes("I")
PAUSED_FLAG = Bytes("P")
STAKED_ASSET = Bytes("SA")
AMOUNT_STAKED = Bytes("AS")
REWARD_ASSET = Bytes("RA")
AMOUNT_REWARDED = Bytes("AR")
TOTAL_REWARDS = Bytes("TR")
FIXED_RATE = Bytes("FR")
BEGIN_TIMESTAMP = Bytes("BT")
END_TIMESTAMP = Bytes("ET")
LAST_UPDATED = Bytes("LU")

@Subroutine(TealType.uint64)
def is_creator() -> Expr:
    return Txn.sender() == Global.creator_address()

@Subroutine(TealType.none)
def is_admin() -> Expr:
    return Assert(Txn.sender() == App.globalGet(ADMIN_ADDRESS))

@Subroutine(TealType.none)
def set_admin(addr: Expr) -> Expr:
    return Seq(
        App.globalPut(ADMIN_ADDRESS, addr),
    )

@Subroutine(TealType.none)
def optin_asset(asset: Expr) -> Expr:
    return Seq(
        InnerTxnBuilder.Begin(),
        InnerTxnBuilder.SetFields({
            TxnField.type_enum: TxnType.AssetTransfer,
            TxnField.xfer_asset: asset,
            TxnField.asset_receiver: Global.current_application_address(),
        }),
        InnerTxnBuilder.Submit(),
    )

@Subroutine(TealType.none)
def send_asset(
    asset: abi.Asset,
    amount: abi.Uint64,
    recipient: abi.Account
) -> Expr:
    return Seq(
        
        # Store amount we actually need to dispense.
        (dispensed_amount := ScratchVar()).store(amount.get()),

        # Check if we're sending the staking asset or the reward asset
        # If we're trying to send more than the account has, use the maximum
        # available value the account has.
        # Deduct the amount from the local state.
        If(asset.asset_id() == App.globalGet(STAKED_ASSET))
        .Then(Seq(
            (amount_staked := ScratchVar()).store(App.localGet(recipient.address(), AMOUNT_STAKED)),
            If(dispensed_amount.load() > amount_staked.load())
            .Then(dispensed_amount.store(amount_staked.load())),
            App.localPut(
                recipient.address(),
                AMOUNT_STAKED,
                App.localGet(recipient.address(), AMOUNT_STAKED) - dispensed_amount.load() # I think this should be (AS - amount) here; will need to store amount in separate scratch slot.
            ),
        ))
        .ElseIf(asset.asset_id() == App.globalGet(REWARD_ASSET))
        .Then(
            (amount_rewarded := ScratchVar()).store(App.localGet(recipient.address(), AMOUNT_REWARDED)),
            If(dispensed_amount.load() > amount_rewarded.load())
            .Then(dispensed_amount.store(amount_rewarded.load())),
            App.localPut(
                recipient.address(),
                AMOUNT_REWARDED,
                App.localGet(recipient.address(), AMOUNT_REWARDED) - dispensed_amount.load()
            ),
        ).Else(Reject()),


        # Send the amount requested or maximum amount available to the recipient.
        InnerTxnBuilder.Begin(),
        InnerTxnBuilder.SetFields(
            {
                TxnField.type_enum: TxnType.AssetTransfer,
                TxnField.xfer_asset: asset.asset_id(),
                TxnField.asset_amount: dispensed_amount.load(),
                TxnField.asset_receiver: recipient.address(),
                TxnField.fee: Int(0),
            }
        ),
        InnerTxnBuilder.Submit(),
    )

@Subroutine(TealType.none)
def is_not_paused() -> Expr:
    return Seq(
        Assert(Not(App.globalGet(PAUSED_FLAG))),
    )

@Subroutine(TealType.none)
def calculate_rewards(addr: Expr) -> Expr:
    return Seq(
        # Skip if not begun
        If(Global.latest_timestamp() < App.globalGet(BEGIN_TIMESTAMP), Return()),

        # Skip if updated since ET
        If(App.localGet(addr, LAST_UPDATED) > App.globalGet(END_TIMESTAMP), Return()), 

        # Calculate time since last update
        # End
        (end := ScratchVar()).store(
            If(Global.latest_timestamp() > App.globalGet(END_TIMESTAMP))
            .Then(App.globalGet(END_TIMESTAMP))
            .Else(Global.latest_timestamp())
        ),
        # Start
        (start := ScratchVar()).store(
            If(App.localGet(addr, LAST_UPDATED) < App.globalGet(BEGIN_TIMESTAMP))
            .Then(App.globalGet(BEGIN_TIMESTAMP))
            .Else(App.localGet(addr, LAST_UPDATED))
        ),
        # Duration
        (duration := ScratchVar()).store(end.load() - start.load()),

        # Calculate rewards
        (rewards := ScratchVar()).store(
            App.localGet(addr, AMOUNT_STAKED) * duration.load() / Int(31557600) * App.globalGet(FIXED_RATE) / Int(10000) # I think there might be truncation issues, especially with very high denominator values.
        ),

        # Remove rewards from global
        App.globalPut(TOTAL_REWARDS, App.globalGet(TOTAL_REWARDS) - rewards.load()), # What happens after "TR" runs out and goes to zero? I think the transaction will fail and any method (i.e. deposit, withdraw) that wants to calculate rewards will also fail. Would anybody be able to take out assets if this happens?

        # Add rewards to local
        App.localPut(addr, AMOUNT_REWARDED, App.localGet(addr, AMOUNT_REWARDED) + rewards.load()),

        # Should we update "LU" here? It seems to be updated in the TEAL code
        App.localPut(addr, LAST_UPDATED, Global.latest_timestamp()),
        App.globalPut(LAST_UPDATED, Global.latest_timestamp()) # Is the Global "LU" just for informational purposes?
    )

router = Router(
    # Name of the contract
    "staking",
    # What to do for each on-complete type when no arguments are passed (bare call)
    BareCallActions(
        # On create only, just approve
        no_op=OnCompleteAction.never(),
        # Just be nice, we _must_ provide _something_ for clear state because it is its own
        # program and the router needs _something_ to build
        clear_state=OnCompleteAction.call_only(Approve()),
    ),
)

@router.method(no_op=CallConfig.CALL, opt_in=CallConfig.CALL)
def deposit(
    axfer: abi.AssetTransferTransaction,
    asset: abi.Asset
) -> Expr:
    """Deposit adds an amount of staked assets to the pool, increasing the
    senders share of the rewards."""
    return Seq(
        # Check the contract isn't paused
        is_not_paused(),

        # Check previous transaction is of type axfer
        Assert(axfer.get().type_enum() == TxnType.AssetTransfer),

        # Confirm sender for this appl and the axfer are the same
        # Note: Do we need to care if it came from the same address?
        Assert(axfer.get().sender() == Txn.sender()),

        # Check the staking asset is being received by the smart contract
        Assert(axfer.get().asset_receiver() == Global.current_application_address()),

        # Need to check that axfer contains the Staked asset
        Assert(axfer.get().xfer_asset() == App.globalGet(STAKED_ASSET)),

        # Calculate rewards
        calculate_rewards(Txn.sender()),

        # Add deposit to users local state
        App.localPut(
            Txn.sender(),
            AMOUNT_STAKED,
            App.localGet(
                Txn.sender(),
                AMOUNT_STAKED
            ) + axfer.get().asset_amount()
        ),

        # Add deposit to global
        App.globalPut(
            Bytes("TS"),
            App.globalGet(Bytes("TS")) + axfer.get().asset_amount()
        ),

        # Success
        Approve(),
    )

@router.method(no_op=CallConfig.ALL, close_out=CallConfig.ALL)
def withdraw(
    asset: abi.Asset,
    amount: abi.Uint64,
    recipient: abi.Account,
) -> Expr:
    """Remove an amount of staked assets or reward assets from the pool."""
    return Seq(
        # Check the contract isn't paused
        is_not_paused(),

        # Calculate rewards
        calculate_rewards(Txn.sender()),

        # Send asset to recipient
        send_asset(asset, amount, recipient),

        # If it's a NoOp we can skip the closeout check
        If(Txn.on_completion() == OnComplete.CloseOut, Seq(
            Assert(Not(App.localGet(recipient.address(), AMOUNT_STAKED))),
            Assert(Not(App.localGet(recipient.address(), AMOUNT_REWARDED))),
        )),

        # Success
        Approve(),
    )

@router.method(no_op=CallConfig.CREATE)
def deploy(
    staking: abi.Asset,
    reward: abi.Asset,
    begin: abi.Uint64,
    end: abi.Uint64,
) -> Expr:
    """Used to deploy the contract, defining assets and times."""
    return Seq(
        # Can only deploy as a new smart contract.
        Assert(Not(Txn.application_id())),

        # User sender as admin.
        set_admin(Txn.sender()),

        # Set staking asset
        App.globalPut(STAKED_ASSET, staking.asset_id()),

        # Set reward asset
        App.globalPut(REWARD_ASSET, reward.asset_id()),

        # Set begin timestamp
        # Must be after LatestTimestamp
        Assert(Gt(begin.get(), Global.latest_timestamp())),
        App.globalPut(BEGIN_TIMESTAMP, begin.get()),

        # Set end timestamp
        # Must be after begin timestamp
        Assert(Gt(end.get(), begin.get())),
        App.globalPut(END_TIMESTAMP, end.get()),

        # Set init flag
        App.globalPut(INIT_FLAG, Int(1)),

        # Success
        Approve(),
    )

@router.method(no_op=CallConfig.CALL)
def init(
    pay: abi.PaymentTransaction,
    staking: abi.Asset,
    reward: abi.Asset,
) -> Expr:
    """Initialise the newly deployed contract, funding it with a minimum
    balance and allowing it to opt in to the request assets."""
    return Seq(
        # Check if admin is initializing the contract
        is_admin(),

        # Only allow calling once, when the init flag is set
        Assert(App.globalGet(INIT_FLAG)),
        App.globalDel(INIT_FLAG),

        # Check previous transaction is a payment transaction
        Assert(pay.get().type_enum() == TxnType.Payment),

        # Check receiver of payment is this smart contract
        Assert(pay.get().receiver() == Global.current_application_address()),

        # Check amount is greater than minimum balance requirement
        Assert(
            Ge(
                Balance(Global.current_application_address()) + pay.get().amount(),
                (Global.min_balance() * (Txn.assets.length() + Int(1))) + (Global.min_txn_fee() * Txn.assets.length())
            )
        ),

        # OptIn to assets
        #(i := ScratchVar()).set(Int(1)),
        For(
            (i := ScratchVar()).store(Int(0)),
            i.load() < Txn.assets.length(),
            i.store(i.load() + Int(1))
        ).Do(
            optin_asset(Txn.assets[i.load()]),
        ),

        #Success
        Approve(),
    )

@router.method(no_op=CallConfig.CALL, close_out=CallConfig.CALL)
def reward(
    rewards: abi.AssetTransferTransaction,
    fixed_rate: abi.Uint64,
    reward: abi.Asset
) -> Expr:
    """Primarily used to supply the initial rewards for the staking contract,
    but can also be used to add additional rewards before the contract ends."""
    return Seq(
        # Check if admin is supplying the rewards
        is_admin(),

        # Check previous transaction is of type axfer
        Assert(rewards.get().type_enum() == TxnType.AssetTransfer),

        # Check receiver of asset transfer is this smart contract
        Assert(rewards.get().asset_receiver() == Global.current_application_address()),

        # Check received asset is reward
        Assert(rewards.get().xfer_asset() == App.globalGet(REWARD_ASSET)),

        # Increase Total Rewards available
        App.globalPut(TOTAL_REWARDS, App.globalGet(TOTAL_REWARDS) + rewards.get().asset_amount()),

        # Set fixed rate
        App.globalPut(FIXED_RATE, fixed_rate.get()),

        # Success
        Approve(),
    )

@router.method(no_op=CallConfig.CALL)
def config(
    paused: abi.Bool,
    admin: abi.Account,
) -> Expr:
    return Seq(
        is_admin(),
        App.globalPut(PAUSED_FLAG, paused.get()),
        set_admin(admin.address()),
    )

if __name__ == '__main__':
    approval, clearstate, contract = router.compile_program(version=CONTRACT_VERSION)

    with open("pyteal_staking.teal", "w") as f:
        f.write(approval)

    with open("pyteal_clear.teal", "w") as f:
        f.write(clearstate)

    with open("pyteal_abi.json", "w") as f:
        f.write(json.dumps(contract.dictify(), indent=4))

