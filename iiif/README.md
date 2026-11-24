# IIIF pipeline

Rod Library's Preservica (Enterprise edition) doesn't publish IIIF, so this folder builds it
on AWS. Public image assets become IIIF Image API services (through
[serverless-iiif](https://github.com/samvera/serverless-iiif)) and IIIF Presentation 3
manifests. Digital Collections can then show them in a viewer, and the Allmaps overlay on
georeferenced maps uses them too.

```
Preservica ── webhook ──► API Gateway ─► webhook Lambda ─┐  (checks Preservica's signature)
           ◄─ nightly check (reconcile Lambda) ──────────┤
                                                          ▼
                                                SQS queue (+ dead-letter queue)
                                                          │
                                                          ▼
           converter Lambda: public? ─► pyPreservica download (Access copy first)
                             ─► libvips tiled pyramidal TIFF ─► S3 tiles bucket ─► serverless-iiif ─┐
                             ─► IIIF manifest (with navPlace) ─► S3 public bucket ──────────────────┤
                                                                                                    ▼
                                                     CloudFront  https://iiif.lib.uni.edu/iiif/3/…
                                                                 https://iiif.lib.uni.edu/manifests/<uuid>.json
```

## What gets published

- **Public items only, by the catalog's rule.** The asset's security tag must be in
  `PUBLIC_SECURITY_TAGS`, every folder above it must be public, and its MODS must not say access
  is restricted. Anything else is withdrawn: its tiles and manifest are deleted, and
  CloudFront's cache is cleared. Use the catalog's read-only service account, which sees only
  public material.
- **Images:** JPEG, TIFF, PNG, GIF, WebP and JPEG 2000 (the container's libvips reads JPEG 2000).
  Each content object becomes one canvas, in Preservica's order. The pipeline takes the Access
  representation when there is one, otherwise Preservation. Other items (PDFs, audio, video,
  documents) get a "skipped" note and keep the Open in Preservica hand-off.
- **Conversion:** images are made upright, converted to 8-bit sRGB (or greyscale), flattened
  if they have transparency, and saved as JPEG-compressed 256-pixel tiles at quality 90. Image
  IDs are `<asset uuid>_0001`, `_0002` and so on.
- **Manifests:** each has the title, summary, date, creator, subjects, places, collection and
  rights from the item's MODS (the ingest's own mapping), plus a link back to Preservica. A
  rightsstatements.org or Creative Commons URI goes in `rights`. Coordinates go in `navPlace`.
- **No repeat work:** the converter compares each file's fixity and the metadata with the last
  run. It skips unchanged items, and rewrites only the manifest when just the metadata changed. To rebuild everything after a change to the conversion or the manifest,
  bump `PIPELINE_VERSION` in `settings.py`.

## Deploying (IT)

You need the AWS SAM CLI, Docker, and an AWS account.

1. **Secrets** in Secrets Manager:
   - `preservica/iiif-service-account`, JSON `{"username": "...", "password": "..."}`
   - `preservica/webhook-secret`, a long random string
2. **This stack:** `cd iiif && sam build && sam deploy --guided`. Leave `ImageOriginDomain`
   empty this first time. Note the `TilesBucketName` output.
3. **serverless-iiif:** deploy it from the AWS Serverless Application Repository (or its
   CloudFormation or Terraform), with `SourceBucket` set to `TilesBucketName`. Check its README
   for the current version and settings.
4. **Connect them:** run `sam deploy` again, with `ImageOriginDomain` set to serverless-iiif's
   endpoint host. Optionally set `DomainName` (e.g. `iiif.lib.uni.edu`) and a us-east-1
   `CertificateArn`, then add a DNS CNAME pointing at the distribution. Check that
   `https://<host>/iiif/3/<id>/info.json` answers once an image has been converted.
5. **Webhooks** (Preservica 6.8 or later, run by an account with the repository manager role):

   ```bash
   export PRESERVICA_SERVER=… PRESERVICA_TENANT=… WEBHOOK_SECRET=…   # plus pyPreservica's credentials
   python -m preservica_iiif subscribe <WebhookUrl output> --trigger INDEXED
   python -m preservica_iiif subscribe <WebhookUrl output> --trigger SECURITY_CHANGED
   python -m preservica_iiif subscribe <WebhookUrl output> --trigger MOVED
   ```

   Without webhooks, the nightly check alone keeps things in step, a day behind.
6. **First fill:** invoke the reconcile function once, or wait for the night. It queues every
   public asset under `RootFolders`.
7. **Catalog:** set two values in `config.yaml` from the stack outputs, then run the ingest. Run
   it after the nightly check, so the index is fresh.

   ```yaml
   iiif_manifest_url_template: "https://iiif.lib.uni.edu/manifests/{uuid}.json"
   iiif_manifest_index_url:   "https://iiif.lib.uni.edu/manifests/index.json"
   ```

   Only items listed in the index get a viewer. Item pages keep a "Download or view in
   Preservica" link under the viewer.

## Running it

| Situation | What to do |
|---|---|
| A message failed three times | It's in the dead-letter queue. Check the convert function's logs, fix the cause, then redrive the queue. |
| `too_large` in the logs (files over `MAX_SOURCE_BYTES`, 3 GB) | Run `python -m preservica_iiif convert <uuid> --no-size-limit` on a machine with disk and memory to spare, such as the catalog server or a Fargate task, using the same container image. |
| An item must come down now | Change its security tag in Preservica (the webhook withdraws it), or run `python -m preservica_iiif withdraw <uuid>`. |
| The nightly check refuses to run | It stops rather than withdraw more than 10% of manifests. Check `RootFolders` and the service account, then run `python -m preservica_iiif reconcile --allow-large-withdrawal`. |
| Recheck everything for changed files | Run `python -m preservica_iiif reconcile --all`. Unchanged items are skipped. |
| Trying it on a laptop | Run `pip install -r iiif/requirements-dev.txt`, then `python -m preservica_iiif convert <uuid> --local out/`. This writes tiles and manifests to `out/`. |

The nightly check walks the folder tree within a Lambda function's 15-minute limit. If the
repository outgrows that, run the same command (`reconcile`) on a schedule on the catalog
server or in Fargate.

## Costs

The costs to watch are:

- **S3 storage for the tiled TIFFs:** roughly the size of the access copies.
- **CloudFront delivery:** this rises with use, since deep zooming fetches many tiles.
- **Lambda conversion time:** mostly one-time, plus a little each night for the check.

The queue, the webhook and the manifests cost very little.

## Tests

```bash
cd iiif && pip install -r requirements-dev.txt && pytest -q && cfn-lint template.yaml
```

The tests use a prebuilt libvips (`pyvips[binary]`), which can't read JPEG 2000. CI also builds
the container and converts a JPEG 2000 inside it.
