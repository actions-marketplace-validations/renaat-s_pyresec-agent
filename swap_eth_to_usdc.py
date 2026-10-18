import os, sys, time
from dotenv import load_dotenv
from web3 import Web3
from eth_account import Account

load_dotenv()

RPC_URL = "https://mainnet.base.org"
PRIVATE_KEY = os.getenv("CDP_WALLET_SECRET")
WALLET = Account.from_key(PRIVATE_KEY)
ADDRESS = WALLET.address

WETH = Web3.to_checksum_address("0x4200000000000000000000000000000000000006")
USDC = Web3.to_checksum_address("0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913")

ERC20_ABI = [
    {"name":"balanceOf","type":"function","inputs":[{"name":"a","type":"address"}],"outputs":[{"name":"","type":"uint256"}],"stateMutability":"view"},
]

# SwapRouter02 on Base - no deadline in params
SWAP_ROUTER_02_ABI = [
    {
        "name": "exactInputSingle",
        "type": "function",
        "inputs": [
            {
                "name": "params",
                "type": "tuple",
                "components": [
                    {"name": "tokenIn", "type": "address"},
                    {"name": "tokenOut", "type": "address"},
                    {"name": "fee", "type": "uint24"},
                    {"name": "recipient", "type": "address"},
                    {"name": "amountIn", "type": "uint256"},
                    {"name": "amountOutMinimum", "type": "uint256"},
                    {"name": "sqrtPriceLimitX96", "type": "uint160"}
                ]
            }
        ],
        "outputs": [{"name": "amountOut", "type": "uint256"}],
        "stateMutability": "payable"
    }
]

def main():
    w3 = Web3(Web3.HTTPProvider(RPC_URL))
    print(f"Network: Base Mainnet (chain_id: {w3.eth.chain_id})")
    print(f"Wallet:  {ADDRESS}")
    
    eth_bal = w3.from_wei(w3.eth.get_balance(Web3.to_checksum_address(ADDRESS)), "ether")
    print(f"ETH Balance: {eth_bal:.8f}")
    
    usdc = w3.eth.contract(address=USDC, abi=ERC20_ABI)
    usdc_bal = usdc.functions.balanceOf(Web3.to_checksum_address(ADDRESS)).call() / 1e6
    print(f"USDC Balance: ${usdc_bal:.6f}")
    
    if eth_bal < 0.001:
        print("Insufficient ETH")
        sys.exit(1)
    
    swap_amount = float(eth_bal) - 0.0003
    swap_amount_wei = w3.to_wei(swap_amount, "ether")
    
    # SwapRouter02 on Base Mainnet
    UNISWAP_ROUTER = Web3.to_checksum_address("0x2626664c2603336E57B271c5C0b26F421741e481")
    router = w3.eth.contract(address=UNISWAP_ROUTER, abi=SWAP_ROUTER_02_ABI)
    
    nonce = w3.eth.get_transaction_count(Web3.to_checksum_address(ADDRESS))
    gas_price = w3.eth.gas_price
    
    print(f"\nSwapping {swap_amount:.8f} ETH -> USDC via SwapRouter02")
    print(f"Fee: 500 (0.05%), Nonce: {nonce}")
    
    # SwapRouter02 exactInputSingle - NO deadline parameter
    swap_params = (
        WETH,           # tokenIn
        USDC,           # tokenOut
        500,            # fee (0.05%)
        Web3.to_checksum_address(ADDRESS),  # recipient
        swap_amount_wei,  # amountIn
        0,              # amountOutMinimum
        0               # sqrtPriceLimitX96
    )
    
    tx = router.functions.exactInputSingle(swap_params).build_transaction({
        "from": Web3.to_checksum_address(ADDRESS),
        "value": swap_amount_wei,
        "gas": 500000,
        "gasPrice": gas_price,
        "nonce": nonce,
        "chainId": 8453,
    })
    
    signed = w3.eth.account.sign_transaction(tx, PRIVATE_KEY)
    tx_hash = w3.eth.send_raw_transaction(signed.raw_transaction)
    print(f"TX sent: {tx_hash.hex()}")
    print("Waiting for confirmation...")
    
    receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=120)
    
    if receipt.status == 1:
        print(f"SUCCESS! Block {receipt.blockNumber}, gas: {receipt.gasUsed}")
    else:
        print(f"FAILED! TX: https://basescan.org/tx/{tx_hash.hex()}")
        sys.exit(1)
    
    time.sleep(2)
    eth_new = w3.from_wei(w3.eth.get_balance(Web3.to_checksum_address(ADDRESS)), "ether")
    usdc_new = usdc.functions.balanceOf(Web3.to_checksum_address(ADDRESS)).call() / 1e6
    
    print(f"\n=== POST-SWAP BALANCES ===")
    print(f"ETH:  {eth_new:.8f}")
    print(f"USDC: ${usdc_new:.6f}")

if __name__ == "__main__":
    main()
