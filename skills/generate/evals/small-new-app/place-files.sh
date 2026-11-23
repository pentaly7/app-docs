#!/usr/bin/env bash
# Copies the sample app into the working folder and makes it a git repo with a GitLab remote,
# so provenance, permalinks and owners can be tested. The remote is never contacted.
set -eu
cp -R "$(dirname "$0")/files/." .
git init -q -b main
git config user.name "Sample Author"
git config user.email "author@example.com"
git remote add origin git@gitlab.example.com:rewards/voucher-api.git
git add -A
GIT_AUTHOR_DATE="2026-11-01T09:00:00+07:00" GIT_COMMITTER_DATE="2026-11-01T09:00:00+07:00" git commit -q -m "voucher-api: redeem, expiry, metrics"
