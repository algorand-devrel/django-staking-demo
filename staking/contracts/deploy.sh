#!/usr/bin/env bash

set -e -u -x -o pipefail

# Remove the directory or set to empty string to use a local goal install.
SB=~/sandbox/sandbox

if [ -z ${SB} ]
then
	GOAL="goal"
else
	GOAL="${SB} goal"
fi

# User first account found in goal if not defined.
CREATOR=""
if [ -z ${CREATOR} ]
then
	CREATOR=$(${GOAL} account list \
		| head -n1 \
		| awk '{print $3}' \
		| tr -d '\r')
fi

CURRENT=$(date +"%s")

BEGIN=$(expr ${CURRENT} + 25)
END=$(expr ${BEGIN} + 325) # 3600 seconds = 1 hour

if [ -n "${SB}" ]
then
	echo "Sandbox being used."
	echo "Copying files..."
	${SB} copyTo staking.teal
	${SB} copyTo clear.teal
fi

# Create staking asset
STAKING_TOTAL=1000000000000000
STAKING_ASSET=$(${GOAL} asset create --creator ${CREATOR} \
	--name "Staking Asset" \
	--unitname "SA" \
	--total ${STAKING_TOTAL} \
	--decimals 6 \
	| grep 'Created asset with asset index' \
	| awk '{print $6}' \
	| tr -d '\r')

# Create reward asset
REWARD_TOTAL=1000000000000
REWARD_ASSET=$(${GOAL} asset create --creator ${CREATOR} \
	--name "Reward Asset" \
	--unitname "RA" \
	--total ${REWARD_TOTAL} \
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
	--global-byteslices 1 --global-ints 10 \
	--local-byteslices 0 --local-ints 3 \
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

# Create transfer of rewards to staking contract
${GOAL} asset send --assetid ${REWARD_ASSET} -f ${CREATOR} \
	-t ${APP_ADDR} \
	-a ${REWARD_TOTAL} \
	-o rewards.txn
# Set the fixed rate and add the rewards to contract
${GOAL} app method --app-id ${APP_ID} -f ${CREATOR} \
	--on-completion "NoOp" \
	--method "reward(axfer,uint64,asset)void" \
	--arg rewards.txn \
	--arg 100 \
	--arg ${REWARD_ASSET}

# Deposit staked asset
${GOAL} asset send -f ${CREATOR} -t ${APP_ADDR} \
	--assetid ${STAKING_ASSET} \
	-a 10000000 \
	-o deposit.txn

${GOAL} app method --app-id ${APP_ID} -f ${CREATOR} \
	--on-completion "OptIn" \
	--method "deposit(axfer,asset)void" \
	--arg deposit.txn \
	--arg ${STAKING_ASSET}

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

echo "Sleeping for 10 seconds..."
sleep 10

# Withdraw Staked
${GOAL} app method --app-id ${APP_ID} -f ${CREATOR} \
	--on-completion "NoOp" \
	--method "withdraw(asset,uint64,account)void" \
	--arg ${STAKING_ASSET} \
	--arg 18446744073709551615 \
	--arg ${CREATOR} \
	--fee 2000

# Withdraw Rewards
${GOAL} app method --app-id ${APP_ID} -f ${CREATOR} \
	--on-completion "CloseOut" \
	--method "withdraw(asset,uint64,account)void" \
	--arg ${REWARD_ASSET} \
	--arg 18446744073709551615 \
	--arg ${CREATOR} \
	--fee 2000

