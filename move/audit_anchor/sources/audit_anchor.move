module audit_anchor::audit_anchor {
    use aptos_framework::event;
    use std::signer;
    use std::vector;

    const EINVALID_ROOT_LENGTH: u64 = 1;

    #[event]
    struct RootAnchored has drop, store {
        actor: address,
        merkle_root: vector<u8>,
    }

    public entry fun anchor_root(account: &signer, merkle_root: vector<u8>) {
        assert!(vector::length(&merkle_root) == 32, EINVALID_ROOT_LENGTH);
        event::emit(RootAnchored {
            actor: signer::address_of(account),
            merkle_root,
        });
    }
}
