# OpenTofu settings for the label stack.
#
# These files are copied into a host repository at .factory/, and tofu
# runs with .factory/ as its working directory. This factory repository
# does not apply them and does not keep a state file. Its CI runs
# tofu init -backend=false, so the backend below is not used here.
#
# State encryption needs OpenTofu 1.7 or newer. The host workflow
# installs 1.13.2. required_version stops an older CLI, which would
# not understand the encryption block.

terraform {
  required_version = ">= 1.13.2"

  required_providers {
    github = {
      source  = "integrations/github"
      version = "6.13.0"
    }
  }

  # Relative to the working directory. In a host that is .factory/,
  # so the file on the host's default branch is .factory/state/terraform.tfstate.
  # Nothing in this repository is shipped under state/.
  backend "local" {
    path = "state/terraform.tfstate"
  }

  # Encrypt state and plan files before they touch disk.
  # The passphrase is var.state_passphrase (TF_VAR_state_passphrase).
  # The file stores a salt, not the passphrase.
  encryption {
    key_provider "pbkdf2" "passphrase" {
      passphrase = var.state_passphrase

      # Recorded inside the encrypted file. Leave it alone, or
      # existing state will not decrypt even if the passphrase is right.
      encrypted_metadata_alias = "passphrase"
    }

    method "aes_gcm" "default" {
      keys = key_provider.pbkdf2.passphrase
    }

    # enforced refuses a plaintext file. There is no unencrypted
    # fallback. The same rules apply to plan files.
    state {
      method   = method.aes_gcm.default
      enforced = true
    }

    plan {
      method   = method.aes_gcm.default
      enforced = true
    }
  }
}
