# Changelog

## [0.2.1] - 2026-10-26

### Added
- CITATION.cff file with citation metadata
- Releases are now archived on Zenodo

### Changed
- Changed the sphinx theme to the ReadTheDocs sphinx theme



## [0.2.0] - 2026-10-21

### Added
- `log.py` module that allows informative `logger` messages to be printed instead of warnings.
- Ability to get `.columns` files from other locations when setting up a project directory.
- Status view now lists termination code if present in log file for model.
- `cli.py` module function to terminate a specific model based on model-ID (now wshown in status view) or PID
- Funding and testing acknowledgement is README.

### Changed
- Several messages that were previously raised as warnings are now displayed as log messages that can be disabled.
- The contents of the `src` directory is now overwritten in the project directory when the setup function is called again.
- Terminal status view uses a new backend that makes it scrollable and less buggy.
- Renamed `ResumePolicy` --> `RestartPolicy`; is more in line with MESA terminology.
- MesaOption names are treated in a case-insensitive way, which is consistent with Fortran's case-insensitivity.

### Fixed
- Various typos in comments, documentation, and README.
- Huge output in some of the docs/examples.
- Got rid of non-essential files by updating .gitignore.

## [0.1.0]
- Initial release for testing
