# no-pipeline

A repository with no workflow or pipeline definition at all. The fixture
collector only picks up files in the three parsed locations, so this case
reaches the classifier as an empty file set, which is exactly what a repo
whose root listing holds no `.github`, `.forgejo`, `.gitea` or `.gitlab-ci.yml`
produces on a forge.
