# RZCode Workflow Skill - Tool Declarations

This directory contains JSON declarations for all MCP tools used by the rzcode-workflow-skill.

## Important Notes

1. **MCP Cloud Implementation**: All tools are implemented as Cloud MCP tools (not HTTP endpoints). They connect to https://rzcode.vip/mcp via the MCP protocol.

2. **Image Upload**: For uploading images, prefer using `scripts/upload_image_files.py` instead of calling `rzcode_upload_images` directly with large base64 data. This avoids loading images into LLM context.

3. **Schema Accuracy**: All inputSchema and outputSchema are based on actual function signatures and return values in softwareCert implementation.

## Tools Overview

### Read Operations (Query)

1. **rzcode_list_projects** - List the current user's RZCode projects with filtering and pagination
2. **rzcode_get_project_status** - Get current project status including source code metadata and image extraction status
3. **rzcode_get_source_code_doc_rules** - Get rules for generating source code documentation (local projects only)
4. **rzcode_get_source_code_meta_requirements** - Get JSON schema and instructions for source code metadata
5. **rzcode_get_image_polished_content_requirements** - Get JSON schema and instructions for polishing image content

### Write Operations (Create/Update)

1. **rzcode_create_project** - Create a new RZCode project for software copyright registration
2. **rzcode_create_or_get_ongoing_task** - Create or retrieve ongoing task (GENERATE_GUIDE_DOCX, GENERATE_APPLICATION_DOCX, EXTRACT_IMAGE_CONTENT)
3. **rzcode_upload_source_code_meta** - Upload source code metadata to local project
4. **rzcode_upload_image_polished_content** - Upload polished content for a specific image
5. **rzcode_upload_images** - Upload images for extraction (use scripts/upload_image_files.py for local projects)

## Tool Declaration Format

Each `.tool.json` file includes:

- **name**: Tool identifier (matches Python function name)
- **description**: What the tool does and any constraints
- **displayName**: Chinese display name
- **category**: "read" or "write"
- **inputSchema**: JSON Schema with parameter types, defaults, enum constraints
- **outputSchema**: JSON Schema for the actual return value
- **examples**: Real usage examples

## File Structure

```
tools/
├── README.md                                          # This file
├── index.json                                         # Tool index by category
│
├── rzcode_list_projects.tool.json
├── rzcode_create_project.tool.json
├── rzcode_get_project_status.tool.json
├── rzcode_create_or_get_ongoing_task.tool.json
├── rzcode_get_source_code_doc_rules.tool.json
├── rzcode_get_source_code_meta_requirements.tool.json
├── rzcode_upload_source_code_meta.tool.json
├── rzcode_get_image_polished_content_requirements.tool.json
├── rzcode_upload_image_polished_content.tool.json
└── rzcode_upload_images.tool.json
```

## MCP Cloud Integration

These tools are exposed as Cloud MCP tools through the softwareCert application:

- **MCP Server URL**: https://rzcode.vip/mcp
- **Authentication**: API Key via X-API-Key header
- **Get API Key**: https://rzcode.vip/settings

## Usage in SKILL.md

All tools are referenced in the SKILL.md manifest:

```yaml
tools:
  - rzcode_list_projects
  - rzcode_create_project
  - rzcode_create_or_get_ongoing_task
  - rzcode_get_project_status
  - rzcode_get_source_code_doc_rules
  - rzcode_get_source_code_meta_requirements
  - rzcode_upload_source_code_meta
  - rzcode_get_image_polished_content_requirements
  - rzcode_upload_image_polished_content
  - rzcode_upload_images
```

## Image Upload Workflow

For local projects, use the Python script instead of direct tool calls:

```bash
export RZCODE_API_KEY="sk.xxxx"
python scripts/upload_image_files.py --project-id 1 /path/to/screenshots/
```

See `scripts/upload_image_files.py` for full documentation and options.
