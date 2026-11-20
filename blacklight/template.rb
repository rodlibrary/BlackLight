# frozen_string_literal: true

# Rails application template for the Preservica Blacklight app.
# Used by bin/setup_blacklight_app; pins Blacklight 9 and skips the MARC
# extensions the upstream demo template installs.

gem 'blacklight', '~> 9.2'

after_bundle do
  auth = Rails.gem_version >= Gem::Version.new('8.0.0') ? '--authentication' : '--devise'
  generate 'blacklight:install', ENV.fetch('BLACKLIGHT_INSTALL_OPTIONS', auth)
  rake 'db:migrate'
end
