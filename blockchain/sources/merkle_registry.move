module auditable_ai_lakehouse::merkle_registry {
    use aptos_framework::event;
    use aptos_framework::vector;

    const EINVALID_ROOT_LENGTH: u64 = 1;

    // ==================== Structs ====================

    struct Registry has key {
        entries: vector<vector<u8>>
    }

    // ==================== Events ====================

    #[event]
    struct MerkleRootStored has store, drop {
        merkle_root: vector<u8>
    }

    // ==================== Initializer ====================

    fun init_module(account: &signer) {
        move_to(account, Registry { entries: vector::empty() });
    }

    // ==================== Write function ====================

    public entry fun store_merkle_root(
        account: &signer, merkle_root: vector<u8>
    ) {
        assert!(merkle_root.length() == 32, EINVALID_ROOT_LENGTH);

        let addr = account.address_of();
        let registry = &mut Registry[addr];

        registry.entries.push_back(merkle_root);

        event::emit(MerkleRootStored { merkle_root });
    }

    // ==================== Test helpers ====================

    #[test_only]
    public fun init_module_for_test(account: &signer) {
        init_module(account);
    }

    // ==================== View function ====================

    #[view]
    public fun get_entry(registry_addr: address, id: u64): vector<u8> {
        let registry = &Registry[registry_addr];
        registry.entries[id]
    }

    #[view]
    public fun get_entry_count(registry_addr: address): u64 {
        let registry = &Registry[registry_addr];
        registry.entries.length()
    }
}
