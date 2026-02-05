// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import { ERC20 } from "@openzeppelin/contracts/token/ERC20/ERC20.sol";
import { ERC20Burnable } from "@openzeppelin/contracts/token/ERC20/extensions/ERC20Burnable.sol";
import { ERC20Permit } from "@openzeppelin/contracts/token/ERC20/extensions/ERC20Permit.sol";

/// @title SourceMint (SRCMNT)
/// @notice Simple, fixed-supply ERC20 with burn + permit.
/// @dev Mints the full initial supply to the deployer (msg.sender) at deployment time.
///      No owner/admin functions = no minting later.
contract SourceMint is ERC20, ERC20Burnable, ERC20Permit {
    constructor(uint256 initialSupply) ERC20("SourceMint", "SRCMNT") ERC20Permit("SourceMint") {
        _mint(msg.sender, initialSupply);
    }
}
