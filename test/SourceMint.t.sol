// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import { Test, console } from "forge-std/Test.sol";
import { SourceMint } from "../src/SourceMint.sol";
import { ERC20Permit } from "@openzeppelin/contracts/token/ERC20/extensions/ERC20Permit.sol";

contract SourceMintTest is Test {
    SourceMint token;

    uint256 constant INITIAL_SUPPLY = 1_000_000 ether;
    address alice = address(0xA11CE);
    address bob = address(0xB0B);
    address user = address(0xf39Fd6e51aad88F6F4ce6aB8827279cffFb92266);

    uint256 private constant PRIVATE_KEY =
        0xac0974bec39a17e36ba4a6b4d238ff944bacb478cbed5efcae784d7bf4f2ff80;

    function setUp() public {
        token = new SourceMint(INITIAL_SUPPLY);
    }

    function test_PermitRejectsExpiredDeadline() public {
        address signer = vm.addr(PRIVATE_KEY);
        address spender = makeAddr("spender");
        address relayer = makeAddr("relayer");
        uint256 value = 100;
        uint256 deadline = block.timestamp + 1 hours;
        uint256 nonceBefore = token.nonces(signer);

        token.transfer(signer, 1000);

        uint256 balanceSignerBefore = token.balanceOf(signer);
        uint256 balanceSpenderBefore = token.balanceOf(spender);

        assertEq(token.allowance(signer, spender), 0);
        assertTrue(relayer != signer);

        (uint8 v, bytes32 r, bytes32 s) =
            vm.sign(PRIVATE_KEY, _permitDigest(signer, spender, value, nonceBefore, deadline));

        vm.warp(block.timestamp + 2 hours);

        vm.prank(relayer);
        vm.expectRevert(
            abi.encodeWithSelector(ERC20Permit.ERC2612ExpiredSignature.selector, deadline)
        );
        token.permit(signer, spender, value, deadline, v, r, s);

        assertEq(token.allowance(signer, spender), 0);
        assertEq(token.nonces(signer), nonceBefore);
        assertEq(token.balanceOf(signer), balanceSignerBefore);
        assertEq(token.balanceOf(spender), balanceSpenderBefore);
    }

    function test_PermitRejectsReusedSignature() public {
        address signer = vm.addr(PRIVATE_KEY);
        address spender = makeAddr("spender");
        address relayer = makeAddr("relayer");
        uint256 value = 100;
        uint256 deadline = block.timestamp + 1 hours;
        uint256 nonceBefore = token.nonces(signer);

        token.transfer(signer, 1000);

        assertEq(token.allowance(signer, spender), 0);
        assertTrue(relayer != signer);

        (uint8 v, bytes32 r, bytes32 s) =
            vm.sign(PRIVATE_KEY, _permitDigest(signer, spender, value, nonceBefore, deadline));

        vm.prank(relayer);
        token.permit(signer, spender, value, deadline, v, r, s);

        assertEq(token.allowance(signer, spender), value);
        assertEq(token.nonces(signer), nonceBefore + 1);

        uint256 nonceAfter = token.nonces(signer);
        vm.expectRevert(
            abi.encodeWithSelector(
                ERC20Permit.ERC2612InvalidSigner.selector,
                ecrecover(_permitDigest(signer, spender, value, nonceAfter, deadline), v, r, s),
                signer
            )
        );
        vm.prank(relayer);
        token.permit(signer, spender, value, deadline, v, r, s);

        assertEq(token.allowance(signer, spender), value);
        assertEq(token.nonces(signer), nonceAfter);
        assertEq(token.balanceOf(signer), 1000);
        assertEq(token.balanceOf(spender), 0);
    }

    function test_PermitValidSignatureFromRelayer() public {
        address signer = vm.addr(PRIVATE_KEY);
        address spender = makeAddr("spender");
        address relayer = makeAddr("relayer");
        uint256 value = 100;
        uint256 deadline = block.timestamp + 1 hours;
        uint256 nonceBefore = token.nonces(signer);

        token.transfer(signer, 1000);

        uint256 balanceSignerBefore = token.balanceOf(signer);
        uint256 balanceSpenderBefore = token.balanceOf(spender);

        assertEq(token.allowance(signer, spender), 0);
        assertTrue(relayer != signer);

        {
            (uint8 v, bytes32 r, bytes32 s) =
                vm.sign(PRIVATE_KEY, _permitDigest(signer, spender, value, nonceBefore, deadline));

            vm.prank(relayer);
            token.permit(signer, spender, value, deadline, v, r, s);
        }

        assertEq(token.allowance(signer, spender), value);
        assertEq(token.nonces(signer), nonceBefore + 1);
        assertEq(token.balanceOf(signer), balanceSignerBefore);
        assertEq(token.balanceOf(spender), balanceSpenderBefore);
    }

    function _permitDigest(
        address signer,
        address spender,
        uint256 value,
        uint256 nonce,
        uint256 deadline
    ) internal view returns (bytes32) {
        bytes32 permitTypehash = keccak256(
            "Permit(address owner,address spender,uint256 value,uint256 nonce,uint256 deadline)"
        );
        bytes32 structHash =
            keccak256(abi.encode(permitTypehash, signer, spender, value, nonce, deadline));
        return keccak256(abi.encodePacked(hex"1901", token.DOMAIN_SEPARATOR(), structHash));
    }

    function test_NoMintFunction() public {
        bytes4 selector = bytes4(keccak256("mint(address,uint256)"));
        bytes memory data = abi.encodeWithSelector(selector, user, 100);

        (bool s,) = address(token).call(data);

        assertFalse(s);
    }

    function test_NoSetFeeFunction() public {
        (bool s,) = address(token).call(abi.encodeWithSignature("setFee(uint256)", 100));

        assertFalse(s);
    }

    function test_NoPauseFunction() public {
        (bool s,) = address(token).call(abi.encodeWithSignature("pause()"));

        assertFalse(s);
    }

    function test_NoOwnerFunction() public {
        (bool s,) = address(token).call(abi.encodeWithSignature("owner()"));

        assertFalse(s);
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

        uint256 transferAmount = 40 ether;

        vm.prank(alice);
        token.transfer(bob, transferAmount);
        assertEq(token.balanceOf(bob), transferAmount);
        assertEq(token.balanceOf(alice), 60 ether);
    }

    function test_BurnReducesSupply() public {
        token.transfer(alice, 50 ether);

        uint256 burnAmount = 10 ether;

        vm.prank(alice);
        token.burn(burnAmount);

        assertEq(token.balanceOf(alice), 40 ether);
        assertEq(token.totalSupply(), INITIAL_SUPPLY - burnAmount);
    }
}
