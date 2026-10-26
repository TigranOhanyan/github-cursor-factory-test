# Issue labels for the repository the host workflow runs in.
#
# Each label is its own github_issue_label. That resource adopts a label
# that already exists (it looks the label up by name) and it leaves every
# other label alone. GitHub's defaults (bug, enhancement, and the rest)
# are not in this map, so they stay.
#
# The other shape, github_issue_labels (plural), owns the whole set and
# deletes labels that are not listed. This stack does not use it.
#
# These descriptions are written to stay true if a label is only ever
# added to an issue and never removed. An issue can carry several of
# them at once. The stack does not attach labels to issues. It only
# makes sure the definitions exist.
#
# GitHub stores a description of at most 100 characters, and a color as
# six hex digits with no leading "#".

locals {
  labels = {
    epic = {
      color       = "5319E7"
      description = "Type: large outcome, broken into stories. Hierarchy is sub-issues, not labels."
    }
    story = {
      color       = "1D76DB"
      description = "Type: user-visible slice of an epic. Hierarchy is sub-issues, not labels."
    }
    task = {
      color       = "006B75"
      description = "Type: one buildable change. Hierarchy is sub-issues, not labels."
    }
    todo = {
      color       = "0E8A16"
      description = "Refined for any builder: clear description and given/when/then criteria."
    }
    in-progress = {
      color       = "FBCA04"
      description = "A builder has started. Do not start a second builder on this issue."
    }
    needs-attention = {
      color       = "D93F0B"
      description = "The pipeline got stuck. A person or a more capable agent has to step in."
    }
  }
}

check "label_descriptions_fit_github" {
  assert {
    condition     = alltrue([for label in values(local.labels) : length(label.description) <= 100])
    error_message = "GitHub label descriptions must be 100 characters or fewer."
  }
}

resource "github_issue_label" "label" {
  # One resource per entry in local.labels. The key is the label name.
  for_each = local.labels

  repository  = local.repository_name
  name        = each.key
  color       = each.value.color
  description = each.value.description

  lifecycle {
    # Dropping a name from local.labels must not delete the GitHub label.
    # prevent_destroy turns that plan into an error instead of a delete.
    prevent_destroy = true
  }
}
