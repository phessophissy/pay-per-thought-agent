// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import "forge-std/Script.sol";
import "../X402PaymentGate.sol";

/**
 * @title DeployPaymentGate
 * @notice Foundry deployment script for X402PaymentGate
 *
 * Usage:
 *   # Deploy to Arbitrum Sepolia
 *   forge script contracts/script/Deploy.s.sol:DeployPaymentGate \
 *     --rpc-url $RPC_URL \
 *     --private-key $PRIVATE_KEY \
 *     --broadcast \
 *     --verify \
 *     --etherscan-api-key $ETHERSCAN_API_KEY
 *
 *   # Dry run (no broadcast)
 *   forge script contracts/script/Deploy.s.sol:DeployPaymentGate \
 *     --rpc-url $RPC_URL \
 *     --private-key $PRIVATE_KEY
 *
 * Required environment variables:
 *   PAYMENT_TOKEN_ADDRESS — ERC-20 token used for payments
 *   OPERATOR_ADDRESS      — Address authorized to manage payments (agent operator)
 */
contract DeployPaymentGate is Script {
    function run() external {
        address paymentToken = vm.envAddress("PAYMENT_TOKEN_ADDRESS");
        address operator = vm.envAddress("OPERATOR_ADDRESS");

        vm.startBroadcast();

        X402PaymentGate gate = new X402PaymentGate(paymentToken, operator);

        vm.stopBroadcast();

        console.log("=== X402PaymentGate Deployed ===");
        console.log("Contract:", address(gate));
        console.log("Payment Token:", paymentToken);
        console.log("Operator:", operator);
    }
}
