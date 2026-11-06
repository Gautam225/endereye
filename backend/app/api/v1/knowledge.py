"""Instructions, glossary, example SQL, documents, and the search tester.

Everyone in the space can read the items; only editors change them or see search stages.
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, File, Query, Request, Response, UploadFile, status

from app.api.deps import CurrentUser, SettingsDep
from app.db.session import SessionDep
from app.rag.parsing import DOCUMENT_TYPES
from app.schemas.knowledge import (
    DocumentLimits,
    DocumentOut,
    DocumentRename,
    ExpressionCreate,
    ExpressionOut,
    ExpressionTestCreate,
    ExpressionTestOut,
    ExpressionTestUpdate,
    ExpressionUpdate,
    ExpressionVersionOut,
    IndexStatus,
    Kind,
    KnowledgeCreate,
    KnowledgeOut,
    KnowledgeUpdate,
    RebuildOut,
    RestoreRequest,
    SearchOut,
    TestRunOut,
)
from app.services import expressions, spaces
from app.services import knowledge as service

router = APIRouter(prefix="/spaces/{space_id}", tags=["knowledge"])
NO_CONTENT = status.HTTP_204_NO_CONTENT


@router.get("/knowledge", response_model=list[KnowledgeOut])
async def list_items(
    space_id: uuid.UUID,
    user: CurrentUser,
    session: SessionDep,
    kind: Kind | None = None,
) -> list[KnowledgeOut]:
    await spaces.get_access(session, user, space_id)
    return [
        KnowledgeOut.model_validate(i) for i in await service.list_items(session, space_id, kind)
    ]


@router.post("/knowledge", response_model=KnowledgeOut, status_code=status.HTTP_201_CREATED)
async def create_item(
    space_id: uuid.UUID,
    body: KnowledgeCreate,
    user: CurrentUser,
    session: SessionDep,
    settings: SettingsDep,
) -> KnowledgeOut:
    """Add an instruction, a glossary term, or an example question with its SQL."""
    access = await spaces.get_access(session, user, space_id, edit=True)
    return KnowledgeOut.model_validate(
        await service.create_item(session, access, user, body, settings)
    )


@router.patch("/knowledge/{item_id}", response_model=KnowledgeOut)
async def update_item(
    space_id: uuid.UUID,
    item_id: uuid.UUID,
    body: KnowledgeUpdate,
    user: CurrentUser,
    session: SessionDep,
    settings: SettingsDep,
) -> KnowledgeOut:
    access = await spaces.get_access(session, user, space_id, edit=True)
    return KnowledgeOut.model_validate(
        await service.update_item(session, access, item_id, body, settings)
    )


@router.delete("/knowledge/{item_id}", status_code=NO_CONTENT)
async def delete_item(
    space_id: uuid.UUID,
    item_id: uuid.UUID,
    user: CurrentUser,
    session: SessionDep,
    settings: SettingsDep,
) -> Response:
    access = await spaces.get_access(session, user, space_id, edit=True)
    await service.delete_item(session, access, item_id, settings)
    return Response(status_code=NO_CONTENT)


# ── SQL expressions (business definitions) ───────────────────────────────────


@router.get("/expressions", response_model=list[ExpressionOut])
async def list_expressions(
    space_id: uuid.UUID, user: CurrentUser, session: SessionDep
) -> list[ExpressionOut]:
    """The space's shared metrics: everyone in it sees them, with owner, version and test state."""
    await spaces.get_access(session, user, space_id)
    return await expressions.list_out(session, space_id)


@router.post("/expressions", response_model=ExpressionOut, status_code=status.HTTP_201_CREATED)
async def create_expression(
    space_id: uuid.UUID,
    body: ExpressionCreate,
    user: CurrentUser,
    session: SessionDep,
    settings: SettingsDep,
) -> ExpressionOut:
    """Add a measure, filter or dimension. It is run against its table first, so one that
    does not work (or is not a safe read-only expression) is refused with the reason. The
    person who adds it is its owner."""
    access = await spaces.get_access(session, user, space_id, edit=True)
    item = await expressions.create_expression(session, access, user, body, settings)
    return await expressions.one_out(session, item)


@router.post("/expressions/run-tests", response_model=TestRunOut)
async def run_all_tests(
    space_id: uuid.UUID, user: CurrentUser, session: SessionDep, settings: SettingsDep
) -> TestRunOut:
    """Run every test of every definition in the space."""
    access = await spaces.get_access(session, user, space_id, edit=True)
    return await expressions.run_all_tests(session, access, settings)


@router.patch("/expressions/{expression_id}", response_model=ExpressionOut)
async def update_expression(
    space_id: uuid.UUID,
    expression_id: uuid.UUID,
    body: ExpressionUpdate,
    user: CurrentUser,
    session: SessionDep,
    settings: SettingsDep,
) -> ExpressionOut:
    """Change a definition. A change to what it computes is run against its tests first, and
    refused (409 `tests_failed`) when one fails, unless `accept_failing_tests` is set. Every
    change to the definition is kept as a new version."""
    access = await spaces.get_access(session, user, space_id, edit=True)
    item = await expressions.update_expression(session, access, user, expression_id, body, settings)
    return await expressions.one_out(session, item)


@router.delete("/expressions/{expression_id}", status_code=NO_CONTENT)
async def delete_expression(
    space_id: uuid.UUID,
    expression_id: uuid.UUID,
    user: CurrentUser,
    session: SessionDep,
    settings: SettingsDep,
) -> Response:
    access = await spaces.get_access(session, user, space_id, edit=True)
    await expressions.delete_expression(session, access, expression_id, settings)
    return Response(status_code=NO_CONTENT)


@router.get("/expressions/{expression_id}/versions", response_model=list[ExpressionVersionOut])
async def list_versions(
    space_id: uuid.UUID, expression_id: uuid.UUID, user: CurrentUser, session: SessionDep
) -> list[ExpressionVersionOut]:
    access = await spaces.get_access(session, user, space_id)
    return await expressions.list_versions(session, access, expression_id)


@router.post(
    "/expressions/{expression_id}/versions/{version}/restore", response_model=ExpressionOut
)
async def restore_version(
    space_id: uuid.UUID,
    expression_id: uuid.UUID,
    version: int,
    body: RestoreRequest,
    user: CurrentUser,
    session: SessionDep,
    settings: SettingsDep,
) -> ExpressionOut:
    """Go back to an earlier definition. It is saved as a new version."""
    access = await spaces.get_access(session, user, space_id, edit=True)
    item = await expressions.restore_version(
        session, access, user, expression_id, version, body.accept_failing_tests, settings
    )
    return await expressions.one_out(session, item)


@router.get("/expressions/{expression_id}/tests", response_model=list[ExpressionTestOut])
async def list_tests(
    space_id: uuid.UUID, expression_id: uuid.UUID, user: CurrentUser, session: SessionDep
) -> list[ExpressionTestOut]:
    access = await spaces.get_access(session, user, space_id)
    return await expressions.list_tests(session, access, expression_id)


@router.post(
    "/expressions/{expression_id}/tests",
    response_model=ExpressionTestOut,
    status_code=status.HTTP_201_CREATED,
)
async def create_test(
    space_id: uuid.UUID,
    expression_id: uuid.UUID,
    body: ExpressionTestCreate,
    user: CurrentUser,
    session: SessionDep,
    settings: SettingsDep,
) -> ExpressionTestOut:
    """Add a test: the definition, run on its table (narrowed by an optional condition), must
    give `expected` (within `tolerance`). It runs once now."""
    access = await spaces.get_access(session, user, space_id, edit=True)
    return ExpressionTestOut.model_validate(
        await expressions.create_test(session, access, user, expression_id, body, settings)
    )


@router.post("/expressions/{expression_id}/tests/run", response_model=TestRunOut)
async def run_tests(
    space_id: uuid.UUID,
    expression_id: uuid.UUID,
    user: CurrentUser,
    session: SessionDep,
    settings: SettingsDep,
) -> TestRunOut:
    access = await spaces.get_access(session, user, space_id, edit=True)
    return await expressions.run_tests(session, access, expression_id, settings)


@router.patch("/expressions/{expression_id}/tests/{test_id}", response_model=ExpressionTestOut)
async def update_test(
    space_id: uuid.UUID,
    expression_id: uuid.UUID,
    test_id: uuid.UUID,
    body: ExpressionTestUpdate,
    user: CurrentUser,
    session: SessionDep,
    settings: SettingsDep,
) -> ExpressionTestOut:
    access = await spaces.get_access(session, user, space_id, edit=True)
    return ExpressionTestOut.model_validate(
        await expressions.update_test(session, access, expression_id, test_id, body, settings)
    )


@router.delete("/expressions/{expression_id}/tests/{test_id}", status_code=NO_CONTENT)
async def delete_test(
    space_id: uuid.UUID,
    expression_id: uuid.UUID,
    test_id: uuid.UUID,
    user: CurrentUser,
    session: SessionDep,
) -> Response:
    access = await spaces.get_access(session, user, space_id, edit=True)
    await expressions.delete_test(session, access, expression_id, test_id)
    return Response(status_code=NO_CONTENT)


# ── Documents ────────────────────────────────────────────────────────────────


@router.get("/documents/limits", response_model=DocumentLimits)
async def document_limits(
    space_id: uuid.UUID, user: CurrentUser, session: SessionDep, settings: SettingsDep
) -> DocumentLimits:
    await spaces.get_access(session, user, space_id)
    return DocumentLimits(file_types=sorted(DOCUMENT_TYPES), max_upload_mb=settings.max_upload_mb)


@router.get("/documents", response_model=list[DocumentOut])
async def list_documents(
    space_id: uuid.UUID, user: CurrentUser, session: SessionDep
) -> list[DocumentOut]:
    await spaces.get_access(session, user, space_id)
    found = await service.list_documents(session, space_id)
    names = await service.uploader_names(session, found)
    return [
        DocumentOut.model_validate(d).model_copy(update={"uploaded_by": names.get(d.created_by)})
        for d in found
    ]


@router.post("/documents", response_model=DocumentOut, status_code=status.HTTP_201_CREATED)
async def upload_document(
    space_id: uuid.UUID,
    request: Request,
    user: CurrentUser,
    session: SessionDep,
    settings: SettingsDep,
    file: Annotated[
        UploadFile, File(description="PDF, Word, PowerPoint, Excel, HTML, Markdown or text")
    ],
) -> DocumentOut:
    """Upload a document. It is saved at once with status `processing`; its text is then read,
    split into chunks and indexed in the background, which ends in `ready`. If it can't be
    read, the document is kept with status `failed` and the reason."""
    access = await spaces.get_access(session, user, space_id, edit=True)
    document = await service.add_document(session, access, user, file, settings)
    service.schedule_indexing(
        request.app.state.sessionmaker, request.app.state.index_tasks, document.id, settings
    )
    return DocumentOut.model_validate(document)


@router.patch("/documents/{document_id}", response_model=DocumentOut)
async def rename_document(
    space_id: uuid.UUID,
    document_id: uuid.UUID,
    body: DocumentRename,
    request: Request,
    user: CurrentUser,
    session: SessionDep,
    settings: SettingsDep,
) -> DocumentOut:
    """Change the title a document is shown and cited under."""
    access = await spaces.get_access(session, user, space_id, edit=True)
    document = await service.rename_document(session, access, document_id, body.title)
    if document.status == "processing":  # its passages carry the title, so they are made again
        service.schedule_indexing(
            request.app.state.sessionmaker, request.app.state.index_tasks, document.id, settings
        )
    return DocumentOut.model_validate(document)


@router.post("/documents/{document_id}/reread", response_model=DocumentOut)
async def reread_document(
    space_id: uuid.UUID,
    document_id: uuid.UUID,
    request: Request,
    user: CurrentUser,
    session: SessionDep,
    settings: SettingsDep,
) -> DocumentOut:
    """Read a document again (after a failure, or to add page numbers to one added earlier)."""
    access = await spaces.get_access(session, user, space_id, edit=True)
    document = await service.prepare_reread(session, access, document_id)
    service.schedule_indexing(
        request.app.state.sessionmaker, request.app.state.index_tasks, document.id, settings
    )
    return DocumentOut.model_validate(document)


@router.delete("/documents/{document_id}", status_code=NO_CONTENT)
async def delete_document(
    space_id: uuid.UUID, document_id: uuid.UUID, user: CurrentUser, session: SessionDep
) -> Response:
    access = await spaces.get_access(session, user, space_id, edit=True)
    await service.delete_document(session, access, document_id)
    return Response(status_code=NO_CONTENT)


# ── Index and search ─────────────────────────────────────────────────────────


@router.get("/index", response_model=IndexStatus)
async def index_status(
    space_id: uuid.UUID, user: CurrentUser, session: SessionDep, settings: SettingsDep
) -> IndexStatus:
    """How much is indexed, and with which models and chunk settings."""
    await spaces.get_access(session, user, space_id, edit=True)
    return await service.status(session, space_id, settings)


@router.post("/index/rebuild", response_model=RebuildOut)
async def rebuild_index(
    space_id: uuid.UUID, user: CurrentUser, session: SessionDep, settings: SettingsDep
) -> RebuildOut:
    """Re-read the schema, items and documents. Use it after changing a model or chunk setting."""
    access = await spaces.get_access(session, user, space_id, edit=True)
    return await service.rebuild(session, access.space.id, settings)


@router.get("/search", response_model=SearchOut)
async def search(
    space_id: uuid.UUID,
    user: CurrentUser,
    session: SessionDep,
    settings: SettingsDep,
    q: Annotated[str, Query(min_length=1, max_length=1000)],
) -> SearchOut:
    """What the AI would be shown for a question, with every stage's rank (editors only)."""
    access = await spaces.get_access(session, user, space_id, edit=True)
    return await service.search(session, access, q.strip(), settings)
