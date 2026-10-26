# Inputs. Neither has a default on purpose.
#
# A default repository would point every host at one repo. A default
# passphrase would sit in git and encrypt every host with the same key.
# The host workflow sets both from the repository it is running in.

variable "github_repository" {
  type        = string
  description = "Repository whose labels this stack manages, as owner/name. The host workflow sets TF_VAR_github_repository from github.repository."
}

variable "state_passphrase" {
  type        = string
  sensitive   = true
  description = "Passphrase for state and plan encryption. At least 16 characters. The host workflow sets TF_VAR_state_passphrase from the repository secret TF_STATE_PASSPHRASE. OpenTofu reads TF_VAR_<name> from the environment."

  validation {
    condition     = length(var.state_passphrase) >= 16
    error_message = "state_passphrase must be at least 16 characters."
  }
}
