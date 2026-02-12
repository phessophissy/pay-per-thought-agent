#!/usr/bin/env python3
"""
Utility script to APPROVE the X402 Payment Gate to spend your ERC-20 tokens.
Required once before running live payments.
"""

import os
import sys
import dotenv
from web3 import Web3

# Load env
dotenv.load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))

def main():
    rpc_url = os.environ.get("RPC_URL")
    private_key = os.environ.get("PRIVATE_KEY") or os.environ.get("CRE_ETH_PRIVATE_KEY")
    gate_address = os.environ.get("X402_CONTRACT_ADDRESS")
    token_address = os.environ.get("PAYMENT_TOKEN_ADDRESS")

    if not all([rpc_url, private_key, gate_address, token_address]):
        print("Error: Missing environment variables. Check .env")
        if not private_key: print("  - Missing PRIVATE_KEY or CRE_ETH_PRIVATE_KEY")
        if not gate_address: print("  - Missing X402_CONTRACT_ADDRESS")
        if not token_address: print("  - Missing PAYMENT_TOKEN_ADDRESS")
        return

    print(f"Connecting to RPC: {rpc_url}")
    w3 = Web3(Web3.HTTPProvider(rpc_url))
    if not w3.is_connected():
        print("Error: Could not connect to RPC")
        return

    account = w3.eth.account.from_key(private_key)
    my_address = account.address
    print(f"Account: {my_address}")
    
    gate_checksum = Web3.to_checksum_address(gate_address)
    token_checksum = Web3.to_checksum_address(token_address)
    
    # ERC-20 ABI (approve, allowance, balanceOf)
    abi = [
        {
            "constant": False,
            "inputs": [{"name": "_spender", "type": "address"}, {"name": "_value", "type": "uint256"}],
            "name": "approve",
            "outputs": [{"name": "", "type": "bool"}],
            "type": "function",
        },
        {
            "constant": True,
            "inputs": [{"name": "_owner", "type": "address"}, {"name": "_spender", "type": "address"}],
            "name": "allowance",
            "outputs": [{"name": "", "type": "uint256"}],
            "type": "function",
        },
        {
            "constant": True,
            "inputs": [{"name": "_owner", "type": "address"}],
            "name": "balanceOf",
            "outputs": [{"name": "balance", "type": "uint256"}],
            "type": "function",
        }
    ]

    token_contract = w3.eth.contract(address=token_checksum, abi=abi)

    # Check Balance
    balance = token_contract.functions.balanceOf(my_address).call()
    print(f"Token Balance: {w3.from_wei(balance, 'ether')} tokens")

    if balance == 0:
        print("⚠️  Warning: Token balance is 0. Payment will fail unless you have tokens!")
        # We proceed anyway, maybe they will mint later.

    # Check Allowance
    allowance = token_contract.functions.allowance(my_address, gate_checksum).call()
    print(f"Current Allowance: {w3.from_wei(allowance, 'ether')} tokens")

    if allowance > 1000 * 10**18:
        print("✅ Sufficient allowance exists. No action needed.")
        return

    # Approve
    print("Approving infinite allowance...")
    tx = token_contract.functions.approve(gate_checksum, 2**256 - 1).build_transaction({
        "from": my_address,
        "nonce": w3.eth.get_transaction_count(my_address),
        "gas": 2000000,
        "gasPrice": int(w3.eth.gas_price * 1.5),  # Add buffer for L2 volatility
    })

    signed_tx = w3.eth.account.sign_transaction(tx, private_key)
    tx_hash = w3.eth.send_raw_transaction(signed_tx.raw_transaction)
    print(f"Transaction sent: {tx_hash.hex()}")
    
    print("Waiting for confirmation...")
    receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=60)
    
    if receipt.status == 1:
        print("✅ Approval successful!")
    else:
        print("❌ Approval failed/reverted.")

if __name__ == "__main__":
    main()
