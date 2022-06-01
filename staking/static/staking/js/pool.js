window.addEventListener('load', function() {
	if (typeof(AlgoSigner) === 'undefined') {
		alert('AlgoSigner is required');
	} else {
		connectWallet();
	}
});

if (document.getElementById('connect')) {
	document.getElementById('connect').addEventListener('click', connectWallet);
}
if (document.getElementById('deposit')) {
	document.getElementById('deposit').addEventListener('click', deposit);
}
if (document.getElementById('withdraw')) {
	document.getElementById('withdraw').addEventListener('click', withdraw);
}
if (document.getElementById('claim')) {
	document.getElementById('claim').addEventListener('click', claim);
}

function connectWallet() {
	AlgoSigner.connect().then(async () => {
		addresses = await AlgoSigner.accounts({ledger: 'SandNet'});
		account = await AlgoSigner.algod({
			ledger: 'SandNet',
			path: '/v2/accounts/'+addresses[0].address,
		});
		document.getElementById('address').text = addresses[0].address;
		document.getElementById('balance').text = account.amount / 1000000 + " Algo";
		document.getElementById('connect').hidden = true;
	});
}

async function deposit() {
	axfer_amount = document.getElementById('amount').value || 0;
	pool_id = document.URL.match(/.*\/(\d*)$/)[1];
	parameters = {
		sender: addresses[0].address,
		amount: parseInt(axfer_amount),
	}
	fetch('/staking/'+pool_id+'/deposit', {
		method: 'POST',
		headers: {
			'Content-Type': 'application/json',
		},
		body: JSON.stringify(parameters),
	})
		.then(response => response.json())
		.then(data => signTransactions(data));
}

function withdraw() {
	console.log("Withdraw");
}

async function claim() {
	console.log("Claiming");
}

async function signTransactions(txns) {
	let signedTxns = await AlgoSigner.signTxn(txns);
	console.log(signedTxns);
	await submit_transactions(signedTxns);
}

async function wait_for_transaction(txid) {
	let resp = await AlgoSigner.algod({
		ledger: 'SandNet',
		path: '/v2/transactions/pending/'+txid,
	})
	console.log("Confirmed: " + resp['confirmed-round']);
}

async function submit_transactions(txns) {
	fetch('/staking/submit', {
		method: 'Post',
		headers: {
			'Content-Type': 'application/json',
		},
		body: JSON.stringify(txns),
	})
		.then(response => response.json())
		.then(data => console.log(data));
}
