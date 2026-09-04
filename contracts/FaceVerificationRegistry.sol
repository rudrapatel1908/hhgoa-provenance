// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

/// @title FaceVerificationRegistry
/// @notice Anchors a cryptographic commitment (SHA-256 digest) of an
///         off-chain media-provenance manifest. Stores NO images, NO
///         biometric embeddings, and NO raw manifest JSON -- only the
///         digest plus minimal audit metadata.
/// @dev    Deploy target: Polygon Amoy testnet (chain id 80002).
contract FaceVerificationRegistry {
    struct Record {
        bytes32 recordHash;   // sha256 of the canonical manifest JSON
        address submitter;
        uint64 timestamp;
        string manifestURI;   // ipfs://<cid>, or "" if IPFS was not used
    }

    /// recordHash => Record
    mapping(bytes32 => Record) private records;

    error DuplicateRecord(bytes32 recordHash);
    error RecordNotFound(bytes32 recordHash);
    error EmptyRecordHash();

    event RecordRegistered(
        bytes32 indexed recordHash,
        address indexed submitter,
        uint64 timestamp,
        string manifestURI
    );

    /// @notice Register a new provenance record. Reverts if this exact
    ///         hash has already been registered -- registrations are
    ///         append-only and non-overwritable by design.
    /// @param recordHash SHA-256 digest of the canonical manifest.
    /// @param manifestURI Optional content-addressed pointer (e.g. IPFS CID).
    function registerRecord(bytes32 recordHash, string calldata manifestURI) external {
        if (recordHash == bytes32(0)) revert EmptyRecordHash();
        if (records[recordHash].timestamp != 0) revert DuplicateRecord(recordHash);

        records[recordHash] = Record({
            recordHash: recordHash,
            submitter: msg.sender,
            timestamp: uint64(block.timestamp),
            manifestURI: manifestURI
        });

        emit RecordRegistered(recordHash, msg.sender, uint64(block.timestamp), manifestURI);
    }

    /// @notice Read-only check: does this exact digest exist on-chain?
    /// @return exists Whether the record is registered.
    /// @return submitter Address that registered it (zero if none).
    /// @return timestamp Registration block timestamp (0 if none).
    function verifyRecord(bytes32 recordHash)
        external
        view
        returns (bool exists, address submitter, uint64 timestamp)
    {
        Record storage r = records[recordHash];
        exists = r.timestamp != 0;
        submitter = r.submitter;
        timestamp = r.timestamp;
    }

    /// @notice Full record retrieval. Reverts if the record doesn't exist,
    ///         so callers can distinguish "not found" from "empty fields".
    function getRecord(bytes32 recordHash) external view returns (Record memory) {
        Record storage r = records[recordHash];
        if (r.timestamp == 0) revert RecordNotFound(recordHash);
        return r;
    }
}
