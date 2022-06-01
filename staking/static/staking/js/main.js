// Various globals.
var updated_rewards;
var urInterval;
var live;

// Attach event listeners to controls on the page if found.
window.addEventListener('load', async function() {
	// Display an alert if AlgoSigner isn't installed.
	if (typeof(AlgoSigner) === 'undefined') {
		alert('AlgoSigner is required');
	} else {
		connectWallet();
	}

	if (document.getElementById('connect')) {
		document.getElementById('connect').addEventListener('click', connectWallet);
	}
	if (document.getElementById('create_asset')) {
		document.getElementById('create_asset').addEventListener('click', createAsset);
	}
	if (document.getElementById('create_pool')) {
		document.getElementById('create_pool').addEventListener('click', createPool);
	}
	if (document.getElementById('deposit')) {
		document.getElementById('deposit').addEventListener('click', deposit);
	}
	if (document.getElementById('withdraw')) {
		document.getElementById('withdraw').addEventListener('click', withdraw);
	}
	if (document.getElementById('withdraw_all')) {
		document.getElementById('withdraw_all').addEventListener('click', withdrawAll);
	}
	if (document.getElementById('claim')) {
		document.getElementById('claim').addEventListener('click', claim);
	}
	if (document.getElementById('current_rewards')) {
		urInterval = setInterval(update_rewards, 1000);
		await update_rewards();
	}
	if (document.getElementById('wallet_select')) {
		document.getElementById('wallet_select').addEventListener('change', changeAddress);
	}
});

function connectWallet() {
	AlgoSigner.connect().then(async () => {
		addresses = await AlgoSigner.accounts({ledger: 'SandNet'});
		await populateWallets(addresses);
	});
}

async function populateWallets(addresses) {
	document.getElementById('connect').hidden = true;
	const wallets = document.getElementById('wallet_select');
	wallets.hidden = false;
	for (var i = 0; i < addresses.length; i++) {
		var w = document.createElement('option');
		w.textContent = addresses[i].address;
		w.value = addresses[i].address;
		wallets.appendChild(w);
	}
	if (document.cookie) {
		let decodedCookie = decodeURIComponent(document.cookie);
		let ca = decodedCookie.split(';');
		let addr;
		for (let i = 0; i < ca.length; i++) {
			let parts = ca[i].split('=');
			wallets.value = parts[1];
		}
		selectWallet();
	}
}

async function changeAddress() {
	const wallet = document.getElementById('wallet_select');
	if (wallet.value == 'Select Account...') return;
	address = wallet.value;
	document.cookie = "account="+address+"; path=/";
	window.location.reload(false);
}

async function selectWallet() {
	const wallet = document.getElementById('wallet_select');
	if (wallet.value == 'Select Account...') return;
	address = wallet.value;
	account = await AlgoSigner.algod({
		ledger: 'SandNet',
		path: '/v2/accounts/'+address,
	});
	//document.getElementById('address').text = address;
	document.getElementById('balance').text = account.amount / 1000000 + " Algo";
	document.getElementById('connect').hidden = true;
	document.cookie = "account="+address+"; path=/";
}

async function createAsset(e) {
	e.preventDefault();
	data = {
		'sender': document.getElementById('wallet_select').value,
		'name': document.getElementById('asset_name').value,
		'unit_name': document.getElementById('asset_unit_name').value,
		'total': parseInt(document.getElementById('asset_total').value),
		'decimals': parseInt(document.getElementById('asset_decimals').value),
	}
	let response = await fetch('/create_asset', {
		method: 'POST',
		headers: {
			'Content-Type': 'application/json',
		},
		body: JSON.stringify(data),
	});
	if (response.ok) {
		let json = await response.json();
		let stxns = await sign_transactions(json);
		if (stxns) {
			let txid = await submit_transactions(stxns);
			if (txid) {
				let asset_id = await wait_for_transaction(txid);
				window.location.reload(false);
			}
		}
	}
}

async function createPool(e) {
	e.preventDefault();
	data = {
		'sender': document.getElementById('wallet_select').value,
		'staking': document.getElementById('staking_asset_id').value,
		'reward': document.getElementById('reward_asset_id').value,
		'begin': document.getElementById('begin_timestamp').value,
		'end': document.getElementById('end_timestamp').value,
	}
	let response = await fetch('/create_pool', {
		method: 'POST',
		headers: {
			'Content-Type': 'application/json',
		},
		body: JSON.stringify(data),
	});
	if (response.ok) {
		let json = await response.json();
		let stxns = await sign_transactions(json);
		if (stxns) {
			let txid = await submit_transactions(stxns);
			if (txid) {
				let txn = await wait_for_transaction(txid);
				if (txn['application-index']) {
					let application_id = txn['application-index'];
					await initPool(application_id);
				}
			}
		}
	}
}

async function initPool(pool_id) {
	data = {
		'sender': document.getElementById('wallet_select').value,
		'fixed-rate': parseFloat(document.getElementById('fixed_rate').value),
		'pool_id': pool_id,
	}
	let response = await fetch('/init_pool', {
		method: 'POST',
		headers: {
			'Content-Type': 'application/json',
		},
		body: JSON.stringify(data),
	});
	if (response.ok) {
		let json = await response.json();
		let stxns = await sign_transactions(json);
		if (stxns) {
			let txid = await submit_transactions(stxns);
			if (txid) {
				let resp = await wait_for_transaction(txid);
				window.location.href = "/";
			}
		}
	}
}

async function deposit() {
	axfer_amount = document.getElementById('amount').value || 0;
	pool_id = document.URL.match(/.*\/(\d*)$/)[1];
	parameters = {
		sender: document.getElementById('wallet_select').value,
		amount: parseInt(axfer_amount),
	}
	let response = await fetch('/'+pool_id+'/deposit', {
		method: 'POST',
		headers: {
			'Content-Type': 'application/json',
		},
		body: JSON.stringify(parameters),
	});
	if (response.ok) {
		let json = await response.json();
		let stxns = await sign_transactions(json);
		if (stxns) {
			let txid = await submit_transactions(stxns);
			if (txid) {
				let resp = await wait_for_transaction(txid);
				window.location.reload(false);
			}
		}
	}
}

async function withdraw() {
	axfer_amount = document.getElementById('amount').value || 0;
	pool_id = document.URL.match(/.*\/(\d*)$/)[1];
	parameters = {
		sender: document.getElementById('wallet_select').value,
		amount: parseInt(axfer_amount),
		all: false,
	}
	let response = await fetch('/'+pool_id+'/withdraw', {
		method: 'POST',
		headers: {
			'Content-Type': 'application/json',
		},
		body: JSON.stringify(parameters),
	});
	if (response.ok) {
		let json = await response.json();
		let stxns = await sign_transactions(json);
		if (stxns) {
			let txid = await submit_transactions(stxns);
			if (txid) {
				let resp = await wait_for_transaction(txid);
				window.location.reload(false);
			}
		}
	}
}

async function withdrawAll() {
	pool_id = document.URL.match(/.*\/(\d*)$/)[1];
	parameters = {
		sender: document.getElementById('wallet_select').value,
		all: true,
	}
	let response = await fetch('/'+pool_id+'/withdraw', {
		method: 'POST',
		headers: {
			'Content-Type': 'application/json',
		},
		body: JSON.stringify(parameters),
	});
	if (response.ok) {
		let json = await response.json();
		let stxns = await sign_transactions(json);
		if (stxns) {
			let txid = await submit_transactions(stxns);
			if (txid) {
				let resp = await wait_for_transaction(txid);
				window.location.reload(false);
			}
		}
	}
}

async function claim() {
	console.log("Claiming");
	axfer_amount = document.getElementById('amount').value || 0;
	pool_id = document.URL.match(/.*\/(\d*)$/)[1];
	parameters = {
		sender: document.getElementById('wallet_select').value,
		amount: parseInt(axfer_amount),
		all: false,
	}
	let response = await fetch('/'+pool_id+'/claim', {
		method: 'POST',
		headers: {
			'Content-Type': 'application/json',
		},
		body: JSON.stringify(parameters),
	});
	if (response.ok) {
		let json = await response.json();
		let stxns = await sign_transactions(json);
		if (stxns) {
			let txid = await submit_transactions(stxns);
			if (txid) {
				let resp = await wait_for_transaction(txid);
				window.location.reload(false);
			}
		}
	}
}

async function sign_transactions(txns) {
	console.log("Sign Transactions");
	let signedTxns;
	try {
		signedTxns = await AlgoSigner.signTxn(txns);
	} catch(err) {
		console.log(err);
		return false;
	}
	return signedTxns;
}

async function wait_for_transaction(txid) {
	console.log("Wait For Transaction");
	document.getElementById('wait').style.display = 'flex';
	let status = await AlgoSigner.algod({
		ledger: 'SandNet',
		path: '/v2/status',
	});
	let current_round = status['last-round'];
	let last_round = current_round + 5;
	while (current_round < last_round) {
		console.log("Checking round: "+current_round);
		try {
			let pending = await AlgoSigner.algod({
				ledger: 'SandNet',
				path: '/v2/transactions/pending/'+txid,
			});

			if (pending['confirmed-round']) {
				document.getElementById('wait').style.display = 'none';
				console.log("Found");
				return pending;
			}
		} catch(err) {
			document.getElementById('wait').style.display = 'none';
			console.log(err);
		}

		await AlgoSigner.algod({
			ledger: 'SandNet',
			path: '/v2/status/wait-for-block-after/'+current_round,
		});
		current_round += 1;
	}
	document.getElementById('wait').style.display = 'none';
	return false;
}

async function submit_transactions(txns) {
	console.log("Submit Transactions");
	let submit_response = await fetch('/submit', {
		method: 'POST',
		headers: {
			'Content-Type': 'application/json',
		},
		body: JSON.stringify(txns),
	});
	if (submit_response.ok) {
		let json = await submit_response.json();
		if (json['success']) {
			return txns[0].txID;
		} else {
			return false;
		}
	}
}

// Update the amount of rewards the user has accumulated with their stake in
// the pool.
async function update_rewards() {
	const amount_staked = parseInt(document.getElementById('amount_staked').text.split(" ")[0]);
	const amount_staked_raw = parseInt(document.getElementById('amount_staked').attributes['value'].value);
	const amount_rewarded = parseInt(document.getElementById('current_rewards').text.split(" ")[0]);
	const amount_rewarded_raw = parseInt(document.getElementById('current_rewards').attributes['value'].value);
	const reward_units = document.getElementById('current_rewards').text.split(" ").pop();
	const begin_timestamp = parseInt(document.getElementById('begin_timestamp').attributes['value'].value);
	const end_timestamp = parseInt(document.getElementById('end_timestamp').attributes['value'].value);
	const last_updated = parseInt(document.getElementById('last_updated').attributes['value'].value);
	const current_timestamp = parseInt(Math.floor(Date.now() / 1000));
	const fixed_rate = parseInt(document.getElementById('fixed_rate').attributes['value'].value);

	if (current_timestamp < begin_timestamp) {
		return
	}

	if (amount_staked == 0) {
		return
	}

	const decimals = 6;
	const dp = 10**decimals;
	const tick = (amount_staked_raw / dp) * fixed_rate / 10000 / 31557600;
	if (current_timestamp < end_timestamp) {
		// Live
		live = true
		if (last_updated > begin_timestamp) {
			duration = current_timestamp - last_updated;
		} else {
			duration = current_timestamp - begin_timestamp;
		}
		updated_rewards = (amount_rewarded_raw / dp) + (tick * duration);
	} else {
		// Ended
		if (last_updated > begin_timestamp) {
			duration = end_timestamp - last_updated;
		} else {
			duration = end_timestamp - begin_timestamp;
		}
		updated_rewards = (amount_rewarded_raw / dp) + (tick * duration);
		clearInterval(urInterval);
		if (live) window.location.reload(false);
	}

	const new_value = Math.round((updated_rewards * dp)) / dp
	document.getElementById('current_rewards').text = new_value + " " + reward_units;
}

