from web3 import Web3
w3 = Web3(Web3.HTTPProvider("https://mainnet.base.org"))
usdc_addr = "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913"
abi = [{"name":"balanceOf","type":"function","inputs":[{"name":"account","type":"address"}],"outputs":[{"name":"","type":"uint256"}],"stateMutability":"view"}]
c = w3.eth.contract(address=Web3.to_checksum_address(usdc_addr), abi=abi)

test_wallet = "0xa97dF9D3752CD96744c0322371dAEC878D284358"
new_server = "0x17eA81BF3bD47Fb6524a09a52DBB77fe1f4ab687"

test_bal = c.functions.balanceOf(Web3.to_checksum_address(test_wallet)).call() / 1e6
server_bal = c.functions.balanceOf(Web3.to_checksum_address(new_server)).call() / 1e6
print(f"Test wallet ({test_wallet[:10]}...): ${test_bal:.6f} USDC")
print(f"Server wallet ({new_server[:10]}...): ${server_bal:.6f} USDC")
