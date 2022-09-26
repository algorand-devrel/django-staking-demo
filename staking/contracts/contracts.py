#!/usr/bin/env python3

import json
from pyteal import *

pragma(compiler_version="^0.18.1")

@Subroutine(TealType.uint64)
def is_creator() -> Expr:
    return Txn.sender() == Global.creator_address()

@Subroutine(TealType.none)
def is_admin() -> Expr:
    return Assert(Txn.sender() == App.globalGet(Bytes("A")))

@Subroutine(TealType.none)
def set_admin(addr: Expr):
    return Seq(
        App.globalPut(Bytes("A"), addr),
    )

@Subroutine(TealType.none)
def optin_asset(asset: Expr):
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
        # Check if we're sending the staking asset or the reward asset
        # If we're trying to send more than the account has, use the maximum
        # available value the account has.
        # Deduct the amount from the local state.
        If(asset.asset_id() == App.globalGet(Bytes("SA")))
        .Then(Seq(
            (amount_staked := ScratchVar()).store(App.localGet(recipient.address(), Bytes("AS"))),
            If(amount.get() > amount_staked.load()).Then(amount.set(amount_staked.load())),
            App.localPut(
                recipient.address(),
                Bytes("AS"),
                App.localGet(recipient.address(), Bytes("AS")) - amount_staked.load()
            ),
        ))
        .Else(Seq(
            (amount_rewarded := ScratchVar()).store(App.localGet(recipient.address(), Bytes("AR"))),
            If(amount.get() > amount_rewarded.load()).Then(amount.set(amount_rewarded.load())),
            App.localPut(
                recipient.address(),
                Bytes("AR"),
                App.localGet(recipient.address(), Bytes("AR")) - amount_rewarded.load()
            ),
        )),
        # Send the amount requested or maximum amount available to the recipient.
        InnerTxnBuilder.Begin(),
        InnerTxnBuilder.SetFields(
            {
                TxnField.type_enum: TxnType.AssetTransfer,
                TxnField.xfer_asset: asset.asset_id(),
                TxnField.asset_amount: amount.get(),
                TxnField.asset_receiver: recipient.address(),
                TxnField.fee: Int(0),
            }
        ),
        InnerTxnBuilder.Submit(),
    )

@Subroutine(TealType.none)
def is_not_paused() -> Expr:
    return Seq(
        Assert(Not(App.globalGet(Bytes("P")))),
    )

@Subroutine(TealType.none)
def calculate_rewards(addr: Expr) -> Expr:
    return Seq(
        # Skip if not begun
        If(Global.latest_timestamp() > App.globalGet(Bytes("BT")), Return()),

        # Skip if updated since ET
        If(App.localGet(addr, Bytes("LU")) < App.globalGet(Bytes("ET")), Return()),

        # Calculate time since last update
        # End
        (end := ScratchVar()).store(
            If(Global.latest_timestamp() > App.globalGet(Bytes("ET")))
            .Then(App.globalGet(Bytes("ET")))
            .Else(Global.latest_timestamp())
        ),
        # Start
        (start := ScratchVar()).store(
            If(App.localGet(addr, Bytes("LU")) < App.globalGet(Bytes("BT")))
            .Then(App.globalGet(Bytes("BT")))
            .Else(App.localGet(addr, Bytes("LU")))
        ),
        # Duration
        (duration := ScratchVar()).store(end.load() - start.load()),

        # Calculate time since last updated
        (rewards := ScratchVar()).store(
            App.localGet(addr, Bytes("AS")) * duration.load() / Int(31557600) * App.globalGet(Bytes("FR")) / Int(10000)
        ),

        # Remove rewards from global
        App.globalPut(Bytes("TR"), App.globalGet(Bytes("TR")) - rewards.load()),

        # Add rewards to local
        App.localPut(addr, Bytes("AR"), App.localGet(addr, Bytes("AR")) + rewards.load()),
    )

router = Router(
    # Name of the contract
    "staking",
    # What to do for each on-complete type when no arguments are passed (bare call)
    BareCallActions(
        # On create only, just approve
        no_op=OnCompleteAction.never(),
        # Just be nice, we _must_ provide _something_ for clear state becuase it is its own
        # program and the router needs _something_ to build
        clear_state=OnCompleteAction.call_only(Approve()),
    ),
)

@router.method(no_op=CallConfig.ALL, opt_in=CallConfig.ALL)
def deposit(
    axfer: abi.AssetTransferTransaction,
    asset: abi.Asset
) -> Expr:
    """Deposit adds an amount of staked assets to the pool, increasing the
    senders share of the rewards."""
    return Seq(
        # Check the contract isn't paused
        is_not_paused(),

        # Confirm sender for this appl and the axfer are the same
        # Note: Do we need to care if it came from the same address?
        Assert(axfer.get().sender() == Txn.sender()),

        # Check the staking asset is being received by the smart contract
        Assert(axfer.get().asset_receiver() == Global.current_application_address()),

        # Calculate rewards
        calculate_rewards(Txn.sender()),

        # Add deposit to users local state
        App.localPut(
            Txn.sender(),
            Bytes("AS"),
            App.localGet(
                Txn.sender(),
                Bytes("AS")
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
            Assert(Not(App.localGet(recipient.address(), Bytes("AS")))),
            Assert(Not(App.localGet(recipient.address(), Bytes("AR")))),
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
        App.globalPut(Bytes("SA"), staking.asset_id()),

        # Set reward asset
        App.globalPut(Bytes("RA"), reward.asset_id()),

        # Set begin timestamp
        # Must be after LatestTimestamp
        Assert(Gt(begin.get(), Global.latest_timestamp())),
        App.globalPut(Bytes("BT"), begin.get()),

        # Set end timestamp
        # Must be after begin timestamp
        Assert(Gt(end.get(), begin.get())),
        App.globalPut(Bytes("ET"), end.get()),

        # Success
        Approve(),
    )

@router.method
def init(
    pay: abi.PaymentTransaction,
    staking: abi.Asset,
    reward: abi.Asset,
) -> Expr:
    """Initialise the newly deployed contract, funding it with a minimum
    balance and allowing it to opt in to the request assets."""
    return Seq(
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

@router.method
def reward(
    rewards: abi.AssetTransferTransaction,
    fixed_rate: abi.Uint64,
    reward: abi.Asset
) -> Expr:
    """Primarily used to supply the initial rewards for the staking contract,
    but can also be used to add additional rewards before the contract ends."""
    return Seq(
        # Check previous transaction is of type axfer
        Assert(rewards.get().type_enum() == TxnType.AssetTransfer),

        # Check receiver of asset transfer is this smart contract
        Assert(rewards.get().asset_receiver() == Global.current_application_address()),

        # Check received asset is reward
        Assert(rewards.get().xfer_asset() == App.globalGet(Bytes("RA"))),

        # Increase Total Rewards available
        App.globalPut(Bytes("TR"), App.globalGet(Bytes("TR")) + rewards.get().asset_amount()),

        # Set fixed rate
        App.globalPut(Bytes("FR"), fixed_rate.get()),

        # Success
        Approve(),
    )

@router.method
def config(
    paused: abi.Bool,
    admin: abi.Account,
) -> Expr:
    return Seq(
        is_admin(),
        App.globalPut(Bytes("P"), Not(Not(paused.get()))),
        set_admin(admin.address()),
    )

if __name__ == '__main__':
    approval, clearstate, abi = router.compile_program(version=6)

    with open("pyteal_staking.teal", "w") as f:
        f.write(approval)

    with open("pyteal_clear.teal", "w") as f:
        f.write(clearstate)

    with open("pyteal_abi.json", "w") as f:
        f.write(json.dumps(abi.dictify()))

