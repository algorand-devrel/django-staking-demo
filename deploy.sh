#!/usr/bin/env bash

set -e -u -x -o pipefail

GOAL="goal"

CREATOR="C5M4M7W32CLQA7BSEEVGDHZZDFVBCUFZEDJHBWMANWQNOXQH6TDLDCYWVE"

CURRENT=$(date +"%s")

BEGIN=$(expr ${CURRENT} - 60)
END=$(expr ${BEGIN} + 60) # 3600 seconds = 1 hour

# Create staking asset
STAKING_ASSET=$(${GOAL} asset create --creator ${CREATOR} \
	--name "Staking Asset" \
	--unitname "SA" \
	--total 1000000000000000 \
	--decimals 6 \
	| grep 'Created asset with asset index' \
	| awk '{print $6}' \
	| tr -d '\r')

# Create reward asset
REWARD_ASSET=$(${GOAL} asset create --creator ${CREATOR} \
	--name "Reward Asset" \
	--unitname "RA" \
	--total 1000000000000 \
	--decimals 6 \
	| grep 'Created asset with asset index' \
	| awk '{print $6}' \
	| tr -d '\r')

# Deploy new staking contract
APP_ID=$(${GOAL} app method --create -f ${CREATOR} \
	--on-completion "NoOp" \
	--method "deploy(asset,asset,uint64,uint64)void" \
	--arg ${STAKING_ASSET} \
	--arg ${REWARD_ASSET} \
	--arg ${BEGIN} \
	--arg ${END} \
	--global-byteslices 1 --global-ints 7 \
	--local-byteslices 0 --local-ints 2 \
	--approval-prog staking.teal \
	--clear-prog clear.teal \
	| grep 'Created app with app index' \
	| awk '{print $6}' \
	| tr -d '\r')

# Find new staking contracts address
APP_ADDR=$(${GOAL} app info --app-id ${APP_ID} \
	| grep 'Application account' \
	| awk '{print $3}' \
	| tr -d '\r')

# Create minimum balance payment to staking contract
${GOAL} clerk send -f ${CREATOR} \
	-t ${APP_ADDR} \
	-a 302000 \
	-o minbal.txn

# Initialise the staking contract with minimum balance. This will have the
# staking contract optin to the required assets.
${GOAL} app method --app-id ${APP_ID} -f ${CREATOR} \
	--on-completion "NoOp" \
	--method "init(pay,asset,asset)void" \
	--arg minbal.txn \
	--arg ${STAKING_ASSET} \
	--arg ${REWARD_ASSET}

# Create asset transfer of rewards into staking contract
${GOAL} asset send -f ${CREATOR} \
	-t ${APP_ADDR} \
	--assetid ${REWARD_ASSET} \
	-a 100000000

# Deposit staked asset
${GOAL} asset send -f ${CREATOR} -t ${APP_ADDR} \
	--assetid ${STAKING_ASSET} \
	-a 10000000 \
	-o deposit.txn

${GOAL} app method --app-id ${APP_ID} -f ${CREATOR} \
	--on-completion "OptIn" \
	--method "deposit(axfer)void" \
	--arg deposit.txn

# Pause Contract
${GOAL} app method --app-id ${APP_ID} -f ${CREATOR} \
	--on-completion "NoOp" \
	--method "config(bool,account)void" \
	--arg true \
	--arg ${CREATOR}

# Unpause Contract
${GOAL} app method --app-id ${APP_ID} -f ${CREATOR} \
	--on-completion "NoOp" \
	--method "config(bool,account)void" \
	--arg false \
	--arg ${CREATOR}

# Withdraw Staked
${GOAL} app method --app-id ${APP_ID} -f ${CREATOR} \
	--on-completion "NoOp" \
	--method "withdraw(asset,uint64,account)void" \
	--arg ${STAKING_ASSET} \
	--arg 0 \
	--arg ${CREATOR} \
	--fee 2000

# Withdraw Rewards
${GOAL} app method --app-id ${APP_ID} -f ${CREATOR} \
	--on-completion "CloseOut" \
	--method "withdraw(asset,uint64,account)void" \
	--arg ${STAKING_ASSET} \
	--arg 0 \
	--arg ${CREATOR} \
	--fee 2000

