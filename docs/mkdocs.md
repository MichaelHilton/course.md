# MkDocs Integration

The MkDocs integration turns a course repository into a course website.
It loads the shared `coursemd` model, makes course data available to pages, generates assignment pages, and can hide unreleased content outside preview mode.

## Install

```bash
pip install "course.md[mkdocs] @ git+https://github.com/ChrisTimperley/course.md.git@v0.1.0"
```

## Configure

Add MkDocs settings to `.coursemd.yml`:

```yaml
integrations:
  mkdocs:
    base_url: https://example.edu/courses/example-101
    project_dir: website
    assignments_url_path: assignments
    include_specs: true
```

Then enable the plugin in `website/mkdocs.yml`:

```yaml
plugins:
  - coursemd:
      config_file: ../.coursemd.yml
  - search
```

`config_file` is optional when `.coursemd.yml` can be discovered from the MkDocs project directory or one of its parents.

## Use

```bash
coursemd site preview
coursemd site build --output-dir build/website
coursemd site build-preview --output-dir build/website-preview
```

Course data is available to Markdown pages through Jinja-style macros.
For example:

```markdown
# Schedule

{{ schedule_table(schedule) }}
```

Assignment Markdown files are read from the configured `paths.assignments` directory and published under `assignments_url_path`.

### Instructor-only blocks

Wrap instructor-only Markdown in the `instructor_only` call-block macro:

```markdown
{% call instructor_only() %}
!!! info "Canvas questions (instructors only)"
    Add the questions here.
{% endcall %}
```

The block is rendered by `coursemd site preview` and `coursemd site build-preview`, but is
omitted from a normal `coursemd site build`. This controls published site output only: anyone
with access to the source repository can still read the block, so never place credentials or
other real secrets in it.

### Preview-only lecture specs

Set `integrations.mkdocs.include_specs: true` to publish lecture specs in `paths.specs_dir`
(default: `specs/`) for instructors without exposing them on the public site. Give each
spec `kind: lecture_spec` and a `date` in its front matter. `coursemd site preview` and
`coursemd site build-preview` publish those files under `/specs/<filename>/`;
`schedule_cards` adds a **View lecture spec** link to the lecture on the same date.
Regular `coursemd site build` omits both the pages and the links. The setting defaults to
`false`.

### Showing unreleased content

Set `integrations.mkdocs.show_unreleased_content: true` to make `released_labs(schedule)`
and `released_assignments(schedule)` return every lab and assignment regardless of their
date or release date. This is useful for previewing a course site before the term starts,
when every lab/assignment date is still in the future and the default date filtering would
otherwise hide everything. The setting defaults to `false`.
