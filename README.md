# Staking Demo

This repository contains a demo of a staking contract and user interface for
users to stake an asset in return for a reward which accrues depending on their
amount and duration staked.

## Design Flow

**Deployer**

 * Deployer deploys a new staking pool contract, specifying:
   * Staking Asset
	 * Reward Asset
	 * Begin Timestamp
	 * End Timestamp
 * Deployer initialises staking pool:
   * Funding minimum balance
	 * Sending reward assets

**User**

 * User has Token A.
 * User opts in to staking app.
 * User deposits Token A into staking app.
 * User accrues Token B over time, based on their position size and duration.
 * User can withdraw Token A and Token B at any time.

**Security**
 * Admin may pause the staking pool at any time
 * If paused, the admin may update the smart contract

## Implementation

### Frontend

A Django (Python) web interface allowing users to connect their wallet and see
what they have staked and their accrued rewards.

The reward rate needs to be implemented the same way as the smart contract, so
that a real-time count of the rewards is matched to what a smart contract would
provide should the user withdraw at the same moment.

### Smart Contracts

A single stateful smart contract is deployed per staking pool. This allows the
smart contract to contain both the logic and also hold the funds (staked assets
and rewards) to keep things simpler.

