#!/usr/bin/env bash

set -e -u -x -o pipefail

GOAL="goal"

CREATOR="VOMJQOMC262EPYQP2QHMVVGJSGFAJCFBGCVKSSS5I3GDVAOQZ5VN6PBSDE"

APP_ID=18

# Freeze
${GOAL} app method --app-id ${APP_ID} -f ${CREATOR} \
	--method "config(bool,account)void" \
	--arg true --arg ${CREATOR} \
	-o freeze.txn

# Update
${GOAL} app method --app-id ${APP_ID} -f ${CREATOR} \
	--method "update()void" \
	--on-completion UpdateApplication \
	--approval-prog staking.teal \
	--clear-prog clear.teal \
	-o update.txn

# Unfreeze
${GOAL} app method --app-id ${APP_ID} -f ${CREATOR} \
	--method "config(bool,account)void" \
	--arg false --arg ${CREATOR} \
	-o unfreeze.txn

cat freeze.txn update.txn unfreeze.txn > update.ctxn
rm freeze.txn update.txn unfreeze.txn

${GOAL} clerk group -i update.ctxn -o update.gtxn
rm update.ctxn

${GOAL} clerk sign -i update.gtxn -o update.sgtxn
rm update.gtxn

${GOAL} clerk rawsend -f update.sgtxn
rm update.sgtxn

