"""GraphQL query templates for Monday.com API."""

# Get item by ID with all information
GET_ITEM_BY_ID = """
query GetItem($itemIds: [ID!]!) {
  items(ids: $itemIds) {
    id
    name
    state
    created_at
    updated_at
    creator_id
    board {
      id
      name
    }
    group {
      id
      title
    }
    column_values {
      id
      text
      value
      type
    }
    assets {
      id
      name
      url
      file_extension
      file_size
      created_at
    }
    updates {
      id
      body
      created_at
      creator_id
      assets {
        id
        name
        url
      }
    }
    subitems {
      id
      name
      column_values {
        id
        text
        value
      }
    }
  }
  complexity {
    before
    after
  }
}
"""

# Get board columns with settings (for status options)
GET_BOARD_COLUMNS = """
query GetBoardColumns($boardIds: [ID!]!) {
  boards(ids: $boardIds) {
    id
    name
    columns {
      id
      title
      type
      settings_str
    }
  }
  complexity {
    before
    after
  }
}
"""

# Get complexity tracking
GET_COMPLEXITY = """
query {
  complexity {
    before
    after
    query
    reset_in_x_seconds
  }
}
"""

# Get document blocks and content
GET_DOC_BLOCKS = """
query GetDocBlocks($docIds: [ID!]!) {
  docs(ids: $docIds) {
    id
    blocks {
      id
      type
      content
    }
  }
}
"""
