"""Commands for managing Monday.com documents."""

import json
from typing import Optional

import typer

from monday_cli.cli import docs_app, get_client
from monday_cli.client.mutations import ADD_CONTENT_FROM_MARKDOWN, CREATE_DOC, DELETE_DOC_BLOCK
from monday_cli.client.queries import EXPORT_MARKDOWN_FROM_DOC, GET_BOARD_COLUMNS, GET_DOC_BLOCKS, GET_DOC_BY_OBJECT_ID, GET_ITEM_BY_ID
from monday_cli.utils.error_handler import AuthenticationError, MondayAPIError, RateLimitError
from monday_cli.utils.output import print_json


def _resolve_doc_column(client, item_id: int, column_name: str):
    """Resolve item and doc column. Returns (item, column_id) or raises typer.Exit."""
    result = client.execute_query(GET_ITEM_BY_ID, {"itemIds": [str(item_id)]})
    items = result.get("items", [])

    if not items:
        typer.secho(f"Item {item_id} not found", fg=typer.colors.YELLOW)
        raise typer.Exit(1)

    item = items[0]
    board = item.get("board")

    if not board:
        typer.secho("Error: Could not determine board for item", fg=typer.colors.RED)
        raise typer.Exit(1)

    columns_result = client.execute_query(GET_BOARD_COLUMNS, {"boardIds": [board["id"]]})
    boards = columns_result.get("boards", [])
    if not boards:
        typer.secho("Error: Could not fetch board columns", fg=typer.colors.RED)
        raise typer.Exit(1)

    columns = boards[0].get("columns", [])
    target_column = next(
        (col for col in columns if col["title"].lower() == column_name.lower()), None
    )

    if not target_column:
        available = ", ".join(f"'{col['title']}'" for col in columns)
        typer.secho(f"Error: Column '{column_name}' not found on board", fg=typer.colors.RED)
        typer.secho(f"Available columns: {available}", fg=typer.colors.YELLOW)
        raise typer.Exit(1)

    if target_column.get("type") != "doc":
        typer.secho(
            f"Error: Column '{column_name}' is not a doc column (type: {target_column.get('type')})",
            fg=typer.colors.RED,
        )
        raise typer.Exit(1)

    return item, target_column["id"]


def _get_existing_doc_object_id(item, column_id: str) -> Optional[str]:
    """Extract the doc object_id from an item's column values, or None.

    The objectId stored in the column value is the object_id in the docs API,
    NOT the internal doc id. Use _resolve_doc_internal_id() to get the internal id.
    """
    for col_val in item.get("column_values", []):
        if col_val["id"] == column_id:
            value_str = col_val.get("value")
            if value_str:
                try:
                    value_data = json.loads(value_str)
                    if isinstance(value_data, dict):
                        doc_id = value_data.get("doc_id")
                        if not doc_id and "files" in value_data:
                            files = value_data.get("files", [])
                            if files:
                                doc_id = files[0].get("objectId") or files[0].get("assetId")
                        if doc_id:
                            return str(doc_id)
                except json.JSONDecodeError:
                    pass
            break
    return None


def _resolve_doc_internal_id(client, object_id: str) -> Optional[str]:
    """Resolve a doc object_id to its internal doc id via the docs API."""
    result = client.execute_query(GET_DOC_BY_OBJECT_ID, {"objectIds": [str(object_id)]})
    docs = result.get("docs", [])
    if docs:
        return str(docs[0]["id"])
    return None


@docs_app.command("get")
def get_doc(
    item_id: Optional[int] = typer.Option(None, "--item-id", "-i", help="ID of the item containing the doc column"),
    column_name: Optional[str] = typer.Option(None, "--column-name", "-n", help="Name of the doc column"),
) -> None:
    """Get document content as Markdown.

    Example:
        monday docs get --item-id 1234567890 --column-name "Monday Doc"
    """
    try:
        if item_id is None:
            typer.secho("Error: Item ID is required. Use --item-id", fg=typer.colors.RED)
            raise typer.Exit(1)

        if column_name is None:
            typer.secho("Error: Column name is required. Use --column-name", fg=typer.colors.RED)
            raise typer.Exit(1)

        client = get_client()

        item, column_id = _resolve_doc_column(client, item_id, column_name)

        object_id = _get_existing_doc_object_id(item, column_id)
        if not object_id:
            typer.secho(
                f"No document found in column '{column_name}' for item {item_id}",
                fg=typer.colors.YELLOW,
            )
            raise typer.Exit(1)

        # Resolve object_id to internal doc id
        internal_id = _resolve_doc_internal_id(client, object_id)
        if not internal_id:
            typer.secho(
                f"Could not resolve document (object_id={object_id})",
                fg=typer.colors.RED,
            )
            raise typer.Exit(1)

        result = client.execute_query(EXPORT_MARKDOWN_FROM_DOC, {"docId": int(internal_id)})
        export = result.get("export_markdown_from_doc", {})

        if export.get("success"):
            typer.echo(export.get("markdown", ""))
        else:
            # Markdown export not supported — fall back to block JSON
            doc_result = client.execute_query(GET_DOC_BLOCKS, {"docIds": [internal_id]})
            docs = doc_result.get("docs", [])
            if not docs:
                typer.secho(f"No content found for document {internal_id}", fg=typer.colors.YELLOW)
                raise typer.Exit(1)
            print_json(docs[0])

    except typer.Exit:
        raise
    except AuthenticationError:
        typer.secho(
            "Error: Invalid API token. Set MONDAY_API_TOKEN environment variable.",
            fg=typer.colors.RED,
        )
        raise typer.Exit(1)
    except RateLimitError as e:
        typer.secho(f"Error: {str(e)}", fg=typer.colors.YELLOW)
        raise typer.Exit(1)
    except MondayAPIError as e:
        typer.secho(f"API Error: {str(e)}", fg=typer.colors.RED)
        raise typer.Exit(1)
    except Exception as e:
        typer.secho(f"Unexpected error: {str(e)}", fg=typer.colors.RED)
        raise typer.Exit(1)


@docs_app.command("append")
def append_doc(
    item_id: Optional[int] = typer.Option(None, "--item-id", "-i", help="ID of the item containing the doc column"),
    column_name: Optional[str] = typer.Option(None, "--column-name", "-n", help="Name of the doc column"),
    content: Optional[str] = typer.Option(None, "--content", "-c", help="Markdown content to append to the document"),
) -> None:
    """Append Markdown content to a document.

    Creates the document if it does not exist, then appends the Markdown content.

    Example:
        monday docs append --item-id 1234567890 --column-name "Monday Doc" --content "# Hello"
    """
    try:
        if item_id is None:
            typer.secho("Error: Item ID is required. Use --item-id", fg=typer.colors.RED)
            raise typer.Exit(1)

        if column_name is None:
            typer.secho("Error: Column name is required. Use --column-name", fg=typer.colors.RED)
            raise typer.Exit(1)

        if content is None:
            typer.secho("Error: Content is required. Use --content", fg=typer.colors.RED)
            raise typer.Exit(1)

        client = get_client()

        item, column_id = _resolve_doc_column(client, item_id, column_name)

        object_id = _get_existing_doc_object_id(item, column_id)
        created = False

        if not object_id:
            create_result = client.execute_mutation(
                CREATE_DOC,
                {"itemId": str(item_id), "columnId": column_id},
            )
            created_doc = create_result.get("create_doc")
            if not created_doc:
                typer.secho("Error: Failed to create document", fg=typer.colors.RED)
                raise typer.Exit(1)
            internal_id = created_doc["id"]
            created = True
        else:
            internal_id = _resolve_doc_internal_id(client, object_id)
            if not internal_id:
                typer.secho(
                    f"Could not resolve document (object_id={object_id})",
                    fg=typer.colors.RED,
                )
                raise typer.Exit(1)

        md_result = client.execute_mutation(
            ADD_CONTENT_FROM_MARKDOWN,
            {"docId": internal_id, "markdown": content},
        )
        result_data = md_result.get("add_content_to_doc_from_markdown", {})
        if not result_data.get("success"):
            error_msg = result_data.get("error", "Unknown error")
            typer.secho(f"Error: Failed to write content: {error_msg}", fg=typer.colors.RED)
            raise typer.Exit(1)

        action = "created" if created else "updated"
        typer.secho(f"✓ Document {action} successfully!", fg=typer.colors.GREEN)
        print_json({"doc_id": internal_id, "item_id": str(item_id), "column_id": column_id})

    except typer.Exit:
        raise
    except AuthenticationError:
        typer.secho(
            "Error: Invalid API token. Set MONDAY_API_TOKEN environment variable.",
            fg=typer.colors.RED,
        )
        raise typer.Exit(1)
    except RateLimitError as e:
        typer.secho(f"Error: {str(e)}", fg=typer.colors.YELLOW)
        raise typer.Exit(1)
    except MondayAPIError as e:
        typer.secho(f"API Error: {str(e)}", fg=typer.colors.RED)
        raise typer.Exit(1)
    except Exception as e:
        typer.secho(f"Unexpected error: {str(e)}", fg=typer.colors.RED)
        raise typer.Exit(1)


def _delete_all_doc_blocks(client, internal_id: str) -> int:
    """Delete all blocks from a document. Returns the number of blocks deleted."""
    deleted = 0
    page = 1
    while True:
        doc_result = client.execute_query(
            GET_DOC_BLOCKS, {"docIds": [internal_id], "limit": 100, "page": page}
        )
        docs = doc_result.get("docs", [])
        if not docs:
            break
        blocks = docs[0].get("blocks", [])
        if not blocks:
            break
        for block in blocks:
            client.execute_mutation(DELETE_DOC_BLOCK, {"blockId": block["id"]})
            deleted += 1
        page += 1
    return deleted


@docs_app.command("put")
def put_doc(
    item_id: Optional[int] = typer.Option(None, "--item-id", "-i", help="ID of the item containing the doc column"),
    column_name: Optional[str] = typer.Option(None, "--column-name", "-n", help="Name of the doc column"),
    content: Optional[str] = typer.Option(None, "--content", "-c", help="Markdown content to write to the document"),
) -> None:
    """Replace document content with Markdown.

    Creates the document if it does not exist. If a document already exists,
    all existing content is deleted before writing the new content.

    Example:
        monday docs put --item-id 1234567890 --column-name "FRD" --content "# Hello\\n\\nWorld"
    """
    try:
        if item_id is None:
            typer.secho("Error: Item ID is required. Use --item-id", fg=typer.colors.RED)
            raise typer.Exit(1)

        if column_name is None:
            typer.secho("Error: Column name is required. Use --column-name", fg=typer.colors.RED)
            raise typer.Exit(1)

        if content is None:
            typer.secho("Error: Content is required. Use --content", fg=typer.colors.RED)
            raise typer.Exit(1)

        client = get_client()

        item, column_id = _resolve_doc_column(client, item_id, column_name)

        object_id = _get_existing_doc_object_id(item, column_id)
        created = False

        if not object_id:
            create_result = client.execute_mutation(
                CREATE_DOC,
                {"itemId": str(item_id), "columnId": column_id},
            )
            created_doc = create_result.get("create_doc")
            if not created_doc:
                typer.secho("Error: Failed to create document", fg=typer.colors.RED)
                raise typer.Exit(1)
            internal_id = created_doc["id"]
            created = True
        else:
            internal_id = _resolve_doc_internal_id(client, object_id)
            if not internal_id:
                typer.secho(
                    f"Could not resolve document (object_id={object_id})",
                    fg=typer.colors.RED,
                )
                raise typer.Exit(1)

            # Delete all existing blocks before writing new content
            deleted_count = _delete_all_doc_blocks(client, internal_id)
            if deleted_count:
                typer.secho(f"Cleared {deleted_count} existing block(s)", fg=typer.colors.YELLOW)

        md_result = client.execute_mutation(
            ADD_CONTENT_FROM_MARKDOWN,
            {"docId": internal_id, "markdown": content},
        )
        result_data = md_result.get("add_content_to_doc_from_markdown", {})
        if not result_data.get("success"):
            error_msg = result_data.get("error", "Unknown error")
            typer.secho(f"Error: Failed to write content: {error_msg}", fg=typer.colors.RED)
            raise typer.Exit(1)

        action = "created" if created else "replaced"
        typer.secho(f"✓ Document content {action} successfully!", fg=typer.colors.GREEN)
        print_json({"doc_id": internal_id, "item_id": str(item_id), "column_id": column_id})

    except typer.Exit:
        raise
    except AuthenticationError:
        typer.secho(
            "Error: Invalid API token. Set MONDAY_API_TOKEN environment variable.",
            fg=typer.colors.RED,
        )
        raise typer.Exit(1)
    except RateLimitError as e:
        typer.secho(f"Error: {str(e)}", fg=typer.colors.YELLOW)
        raise typer.Exit(1)
    except MondayAPIError as e:
        typer.secho(f"API Error: {str(e)}", fg=typer.colors.RED)
        raise typer.Exit(1)
    except Exception as e:
        typer.secho(f"Unexpected error: {str(e)}", fg=typer.colors.RED)
        raise typer.Exit(1)
