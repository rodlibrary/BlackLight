# frozen_string_literal: true

# Rails application template for the Preservica Blacklight app.
# Used by bin/setup_blacklight_app; pins Blacklight 9 and skips the MARC
# extensions the upstream demo template installs.

gem 'blacklight', '~> 9.2'

after_bundle do
  # No logins: the site has no bookmarks or accounts, so Blacklight is installed
  # without an authentication option (neither --devise nor --authentication).
  # Set BLACKLIGHT_INSTALL_OPTIONS to add one later.
  generate 'blacklight:install', ENV.fetch('BLACKLIGHT_INSTALL_OPTIONS', '')
  rake 'db:migrate'
end
