param(
  [string]$Prefix = "v1.0.0-canary"
)

# Fail on error
$ErrorActionPreference = 'Stop'

function Ensure-CleanTree {
  $status = git status --porcelain
  if ($status) {
    Write-Error "Working tree not clean. Commit or stash changes first."
  }
}

function Next-Tag($prefix) {
  $tags = git tag --list "$prefix.*" | Sort-Object
  if (-not $tags) { return "$prefix.1" }
  $last = $tags[-1]
  if ($last -match "(\d+)$") {
    $n = [int]$Matches[1] + 1
    return "$prefix.$n"
  }
  return "$prefix.1"
}

Ensure-CleanTree
$tag = Next-Tag $Prefix

# Idempotent: if tag exists, just print and exit 0
$exists = git tag --list $tag
if ($exists) {
  Write-Host "Tag already exists: $tag"
  exit 0
}

git tag -a $tag -m "Release $tag"
git push origin $tag
Write-Host "Created and pushed tag $tag"
