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

# Get board groups
GET_BOARD_GROUPS = """
query GetBoardGroups($boardIds: [ID!]!) {
  boards(ids: $boardIds) {
    id
    name
    groups {
      id
      title
      color
      position
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
query GetDocBlocks($docIds: [ID!]!, $limit: Int, $page: Int) {
  docs(ids: $docIds) {
    id
    blocks(limit: $limit, page: $page) {
      id
      type
      content
    }
  }
}
"""

# Resolve object_id (from item column values) to internal doc id
GET_DOC_BY_OBJECT_ID = """
query GetDocByObjectId($objectIds: [ID!]) {
  docs(object_ids: $objectIds) {
    id
    object_id
  }
  complexity {
    before
    after
  }
}
"""

# Export document content as markdown (requires internal doc id, not object_id)
EXPORT_MARKDOWN_FROM_DOC = """
query ExportMarkdownFromDoc($docId: ID!) {
  export_markdown_from_doc(docId: $docId) {
    success
    markdown
    error
  }
}
"""

# Get boards with filtering and pagination
GET_BOARDS = """
query GetBoards($limit: Int, $page: Int, $state: State, $workspace_ids: [ID!]) {
  boards(limit: $limit, page: $page, state: $state, workspace_ids: $workspace_ids) {
    id
    name
    description
    state
    board_kind
    items_count
    updated_at
    workspace {
      id
      name
    }
  }
  complexity {
    before
    after
  }
}
"""

# Get items from a board with cursor-based pagination
GET_BOARD_ITEMS = """
query GetBoardItems($boardIds: [ID!]!, $limit: Int, $cursor: String) {
  boards(ids: $boardIds) {
    id
    name
    items_page(limit: $limit, cursor: $cursor) {
      cursor
      items {
        id
        name
        state
        created_at
        updated_at
        creator {
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
          type
        }
      }
    }
  }
  complexity {
    before
    after
  }
}
"""

# Get subitems from a parent item
GET_ITEM_SUBITEMS = """
query GetItemSubitems($itemIds: [ID!]!) {
  items(ids: $itemIds) {
    id
    name
    board {
      id
      name
    }
    subitems {
      id
      name
      state
      created_at
      updated_at
      creator {
        id
        name
      }
      board {
        id
        name
      }
      column_values {
        id
        text
        type
      }
    }
  }
  complexity {
    before
    after
  }
}
"""

# Get next page of items using cursor (more efficient than nested boards query)
GET_NEXT_ITEMS_PAGE = """
query GetNextItemsPage($cursor: String!, $limit: Int) {
  next_items_page(cursor: $cursor, limit: $limit) {
    cursor
    items {
      id
      name
      state
      created_at
      updated_at
      creator {
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
        type
      }
    }
  }
  complexity {
    before
    after
  }
}
"""

# Get workspaces
GET_WORKSPACES = """
query GetWorkspaces($limit: Int, $ids: [ID!], $membership_kind: WorkspaceMembershipKind) {
  workspaces(limit: $limit, ids: $ids, membership_kind: $membership_kind) {
    id
    name
    kind
    description
    account_product {
      id
      kind
    }
  }
  complexity {
    before
    after
  }
}
"""
