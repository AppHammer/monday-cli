"""Commands for managing Monday.com documents."""

import json
from typing import Optional

import typer

from monday_cli.cli import docs_app, get_client
from monday_cli.client.mutations import CREATE_DOC, CREATE_DOC_BLOCK
from monday_cli.client.queries import GET_BOARD_COLUMNS, GET_DOC_BLOCKS, GET_ITEM_BY_ID
from monday_cli.utils.error_handler import AuthenticationError, MondayAPIError, RateLimitError
from monday_cli.utils.output import print_json


@docs_app.command("create")
def create_doc(
    item_id: int = typer.Argument(..., help="ID of the item containing the doc column"),
    column_name: str = typer.Argument(..., help="Name of the doc column (e.g., 'Monday Doc')"),
    content: Optional[str] = typer.Option(
        None,
        "--content",
        "-c",
        help="Initial text content for the document",
    ),
) -> None:
    """Create a document in a doc column.

    Looks up the column by name and creates a new document in that column.
    Optionally adds initial text content to the document.

    Example:
        monday docs create 1234567890 "Monday Doc"

        monday docs create 1234567890 "Notes" --content "Meeting notes here"
    """
    try:
        client = get_client()

        # Get the item to find its board ID
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

        board_id = board["id"]

        # Get board columns to find the doc column by name
        columns_result = client.execute_query(GET_BOARD_COLUMNS, {"boardIds": [board_id]})

        boards = columns_result.get("boards", [])
        if not boards:
            typer.secho("Error: Could not fetch board columns", fg=typer.colors.RED)
            raise typer.Exit(1)

        board_data = boards[0]
        columns = board_data.get("columns", [])

        # Find the column by name (case-insensitive)
        target_column = None
        column_name_lower = column_name.lower()
        for col in columns:
            if col["title"].lower() == column_name_lower:
                target_column = col
                break

        if not target_column:
            available_columns = ", ".join(f"'{col['title']}'" for col in columns)
            typer.secho(
                f"Error: Column '{column_name}' not found on board",
                fg=typer.colors.RED,
            )
            typer.secho(f"Available columns: {available_columns}", fg=typer.colors.YELLOW)
            raise typer.Exit(1)

        # Validate column is a doc type
        if target_column.get("type") != "doc":
            typer.secho(
                f"Error: Column '{column_name}' is not a doc column (type: {target_column.get('type')})",
                fg=typer.colors.RED,
            )
            raise typer.Exit(1)

        column_id = target_column["id"]

        # Create the document
        create_result = client.execute_mutation(
            CREATE_DOC,
            {"itemId": str(item_id), "columnId": column_id},
        )

        created_doc = create_result.get("create_doc")
        if not created_doc:
            typer.secho("Error: Failed to create document", fg=typer.colors.RED)
            raise typer.Exit(1)

        doc_id = created_doc["id"]

        # If content is provided, add a text block
        if content:
            block_content = json.dumps({
                "alignment": "left",
                "direction": "ltr",
                "deltaFormat": [{"insert": content}],
            })

            client.execute_mutation(
                CREATE_DOC_BLOCK,
                {
                    "docId": doc_id,
                    "type": "normal_text",
                    "content": block_content,
                },
            )

        typer.secho("✓ Document created successfully!", fg=typer.colors.GREEN)
        print_json({"doc_id": doc_id, "item_id": str(item_id), "column_id": column_id})

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


@docs_app.command("get")
def get_doc(
    item_id: int = typer.Argument(..., help="ID of the item containing the doc column"),
    column_name: str = typer.Argument(..., help="Name of the doc column (e.g., 'Monday Doc')"),
) -> None:
    """Get document content by item ID and column name.

    Looks up the doc column by name and retrieves the document content.

    Example:
        monday docs get 1234567890 "Monday Doc"
    """
    try:
        client = get_client()

        # Get the item to find its board ID and column values
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

        board_id = board["id"]

        # Get board columns to find the doc column by name
        columns_result = client.execute_query(GET_BOARD_COLUMNS, {"boardIds": [board_id]})

        boards = columns_result.get("boards", [])
        if not boards:
            typer.secho("Error: Could not fetch board columns", fg=typer.colors.RED)
            raise typer.Exit(1)

        board_data = boards[0]
        columns = board_data.get("columns", [])

        # Find the column by name (case-insensitive)
        target_column = None
        column_name_lower = column_name.lower()
        for col in columns:
            if col["title"].lower() == column_name_lower:
                target_column = col
                break

        if not target_column:
            available_columns = ", ".join(f"'{col['title']}'" for col in columns)
            typer.secho(
                f"Error: Column '{column_name}' not found on board",
                fg=typer.colors.RED,
            )
            typer.secho(f"Available columns: {available_columns}", fg=typer.colors.YELLOW)
            raise typer.Exit(1)

        # Validate column is a doc type
        if target_column.get("type") != "doc":
            typer.secho(
                f"Error: Column '{column_name}' is not a doc column (type: {target_column.get('type')})",
                fg=typer.colors.RED,
            )
            raise typer.Exit(1)

        column_id = target_column["id"]

        # Find the doc_id from the item's column values
        column_values = item.get("column_values", [])
        doc_id = None

        for col_val in column_values:
            if col_val["id"] == column_id:
                value_str = col_val.get("value")
                if value_str:
                    try:
                        value_data = json.loads(value_str)
                        # Doc column value contains {"files": [{"fileType": "DOC", "assetId": XXX}]}
                        # or {"doc_id": XXX} depending on API version
                        if isinstance(value_data, dict):
                            doc_id = value_data.get("doc_id")
                            if not doc_id and "files" in value_data:
                                files = value_data.get("files", [])
                                if files:
                                    doc_id = files[0].get("assetId")
                    except json.JSONDecodeError:
                        pass
                break

        if not doc_id:
            typer.secho(
                f"No document found in column '{column_name}' for item {item_id}",
                fg=typer.colors.YELLOW,
            )
            raise typer.Exit(1)

        # Query the document blocks
        doc_result = client.execute_query(GET_DOC_BLOCKS, {"docIds": [str(doc_id)]})

        docs = doc_result.get("docs", [])
        if not docs:
            typer.secho(f"Document {doc_id} not found", fg=typer.colors.YELLOW)
            raise typer.Exit(1)

        print_json(docs[0])

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
