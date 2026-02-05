// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import { Script } from "forge-std/Script.sol";
import { SourceMint } from "../src/SourceMint.sol";

contract DeploySourceMint is Script {
    function run() external returns (SourceMint token) {
        // PRIVATE_KEY should be a 0x... hex string. We parse it as bytes32 for convenience.
        bytes32 pkBytes = vm.envBytes32("PRIVATE_KEY");
        uint256 deployerPk = uint256(pkBytes);

        // Optional override
        uint256 initialSupply = vm.envOr("INITIAL_SUPPLY", uint256(1_000_000 ether));

        vm.startBroadcast(deployerPk);
        token = new SourceMint(initialSupply);
        vm.stopBroadcast();

        // Write deployment JSON: deployments/<chainId>.json
        string memory obj = "deployment";
        vm.serializeString(obj, "name", token.name());
        vm.serializeString(obj, "symbol", token.symbol());
        vm.serializeUint(obj, "chainId", block.chainid);
        vm.serializeAddress(obj, "address", address(token));
        vm.serializeUint(obj, "initialSupply", initialSupply);
        string memory json = vm.serializeUint(obj, "deployedAtUnix", block.timestamp);

        string memory path = string.concat("deployments/", vm.toString(block.chainid), ".json");
        vm.writeJson(json, path);
    }
}
