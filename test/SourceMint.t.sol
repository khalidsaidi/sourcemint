// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import { Test } from "forge-std/Test.sol";
import { SourceMint } from "../src/SourceMint.sol";

contract SourceMintTest is Test {
    SourceMint token;

    uint256 constant INITIAL_SUPPLY = 1_000_000 ether;
    address alice = address(0xA11CE);
    address bob = address(0xB0B);

    function setUp() public {
        token = new SourceMint(INITIAL_SUPPLY);
    }

    function test_Metadata() public view {
        assertEq(token.name(), "SourceMint");
        assertEq(token.symbol(), "SRCMNT");
        assertEq(token.decimals(), 18);
    }

    function test_InitialSupplyMintedToDeployer() public view {
        assertEq(token.totalSupply(), INITIAL_SUPPLY);
        assertEq(token.balanceOf(address(this)), INITIAL_SUPPLY);
    }

    function test_Transfer() public {
        token.transfer(alice, 100 ether);
        assertEq(token.balanceOf(alice), 100 ether);
        assertEq(token.balanceOf(address(this)), INITIAL_SUPPLY - 100 ether);

        vm.prank(alice);
        token.transfer(bob, 40 ether);
        assertEq(token.balanceOf(bob), 40 ether);
        assertEq(token.balanceOf(alice), 60 ether);
    }

    function test_BurnReducesSupply() public {
        token.transfer(alice, 50 ether);

        vm.prank(alice);
        token.burn(10 ether);

        assertEq(token.balanceOf(alice), 40 ether);
        assertEq(token.totalSupply(), INITIAL_SUPPLY - 10 ether);
    }
}
