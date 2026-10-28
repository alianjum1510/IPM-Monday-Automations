# Claude Implementation Brief: Refactor to a Scalable, FastAPI-Only monday.com Automation Platform

## Objective
Throhly reserach before doing it actually. Make sure how many feature blocks do I need can this be done in one feature block or do I need multiple feature blocks actually, After doing it create a PLAN.md file which will have all the details of what you'll be doing and then the implementation stuff. DOn't implement Untill I ask you to implement it specifically. 
Refactor the existing integration so that **Company Enrichment and Customer Name Split run under one FastAPI application, one monday.com app, and one shared production deployment**.

The architecture must support adding future automation features with minimal changes. Existing Company Enrichment behavior is already working and must not regress.

Do not begin by rewriting everything. Inspect the repository, understand the existing implementation, identify the minimum safe refactoring steps, and execute them incrementally.

## 1. Inspect the Existing Repository

Start with the `merge-customer-company-app` branch and inspect the current working tree before making changes.

The last known integration commit was `8698ad8 Working Company Enrichment merged`, but verify the actual repository state rather than assuming it is unchanged.

Inspect:

- `main.py`
- `company_enrichment/`
- `customer_name_split_py/`
- `monday_logging.py`
- All requirements files
- Existing tests
- `Procfile`
- `.mondaycoderc`
- Environment-variable loading and authentication logic

Run the complete existing test suite and record the baseline.

Do not discard uncommitted changes.

## 2. Refactor to FastAPI Only

The target architecture must use FastAPI as the only HTTP framework.

Currently, the unified application mounts a Flask Company Enrichment application through `a2wsgi`, while Customer Name Split already uses FastAPI.

Remove this dual-framework arrangement safely.

### Required changes

1. Extract Company Enrichment business logic from its Flask-specific request-handling layer into framework-independent service functions where necessary.
2. Expose Company Enrichment through a FastAPI router.
3. Keep Customer Name Split as a separate feature module with its own FastAPI router or equivalent route handlers.
4. Remove the Flask-to-ASGI adapter and Flask-specific runtime dependencies once they are no longer required.
5. Update requirements and tests accordingly.
6. Preserve all existing enrichment behavior, field mappings, API integrations, validation, retry logic, logging semantics, and error handling.

Do not mechanically translate every Flask function into a new FastAPI function if it can remain an ordinary Python service function.

Keep business logic separate from HTTP request parsing and response construction.

Do not rewrite the enrichment algorithm, AI prompts, mapping logic, or data-processing rules merely to change frameworks.

## 3. Establish a Modular Architecture

Use a structure similar to the following, adapting it to the existing repository rather than moving files unnecessarily:

```text
main.py
requirements.txt

app/
  core/
    config.py
    security.py
    logging.py
    monday_client.py

  api/
    router.py
    health.py

  features/
    company_enrichment/
      router.py
      service.py
      schemas.py
      tests/

    customer_name_split/
      router.py
      service.py
      schemas.py
      processors/
        kunden.py
        warm_lead.py
      tests/

  tests/
    test_routing.py
    test_authentication.py
    test_integration.py
```

This is a proposed target structure, not a requirement to move every existing file. Preserve useful existing modules and minimize unnecessary churn.

### Architectural responsibilities

- `main.py`: Create the FastAPI application and register the main router.
- `core/config.py`: Centralize configuration and environment-variable validation.
- `core/security.py`: Reusable monday.com request authentication.
- `core/logging.py`: Structured logging and correlation IDs.
- `core/monday_client.py`: Shared monday.com API client, where doing so preserves existing behavior.
- `api/router.py`: Register feature routers.
- Feature routers: Validate HTTP input and delegate to feature services.
- Feature services: Implement the actual business logic.
- Feature-specific processors: Contain board-specific processing rules.

Avoid circular imports, duplicated authentication logic, and global mutable state.

Do not introduce unnecessary abstractions, microservices, databases, queues, or third-party dependencies without a concrete requirement.

## 4. Implement Explicit Feature Routing

Use independent routes for each automation.

Recommended routes:

| Purpose | Route |
|---|---|
| Existing Company Enrichment compatibility | `POST /` |
| Company Enrichment canonical route | `POST /company-enrichment` |
| Customer Name Split | `POST /customer-name-split` |
| Customer Name Split compatibility route | `POST /monday/split-name` |
| Health check | `GET /health` |

Keep `POST /` working for Company Enrichment because the existing monday.com block may depend on it.

Do not route based only on board ID. A single board may use more than one automation.

Do not trust an arbitrary client-supplied feature name to decide which handler runs. The configured endpoint must determine the feature, with any additional payload validation applied afterward.

Where practical, register features through a central router so adding another feature requires creating its module, registering its router, adding tests, and configuring its monday.com block.

Avoid a large conditional dispatcher that must be edited for every new feature.

## 5. Preserve Customer Name Split Behavior

Keep the current behavior unchanged.

### Kunden boards

- Board IDs: `5099245948` and `5094068289`.
- Split the item name into Teil 1 and Teil 2 according to the existing rules.
- Preserve the behavior for short names, including clearing Teil 2 where required.
- Avoid unnecessary writes when the desired values already exist.

### Warm Lead

- Board ID: `5106281544`.
- If Company / Customer Name exceeds 100 characters, shorten it according to the existing last-space rule.
- Place the remaining text in Company / Customer Name 2.
- If the name is already within the limit, do not rewrite it.

Preserve all existing column IDs, API behavior, and board-specific rules unless a verified defect requires a separately justified change.

## 6. Verify the monday.com App and Action Blocks

Do not assume the code refactor alone will resolve the current routing issue.

Inspect the actual monday.com Developer Center configuration and determine:

1. Which app owns the working Company Enrichment deployment.
2. Whether Customer Name Split can be added as a separate action feature to that same app.
3. Whether both features can be connected to the same server-side deployment.
4. Which subroute is configured for each feature.
5. Whether the current blocks use monday workflows Automation block features or a deprecated legacy integration feature.
6. Whether the configured signing secret and environment variables are available to the unified deployment.

Use the current monday.com workflow infrastructure for new or migrated automation features rather than building on deprecated legacy sentence-builder features.

### Desired configuration

**One monday.com app: Company Management**

- Action feature 1: Company Enrichment
  - Uses the existing deployment.
  - Preserves the existing root route or uses `/company-enrichment` if safely configured.
- Action feature 2: Customer Name Split
  - Uses the same deployment.
  - Uses `/customer-name-split`.

Both action features must be independently selectable and independently testable.

Do not create a second production deployment merely to add Customer Name Split.

Do not create a new action block for every board or every workflow. Reuse the relevant block wherever its inputs and behavior fit.

If the existing platform configuration prevents the proposed arrangement, document the verified limitation and propose the smallest safe alternative before changing production.

## 7. Authentication and Configuration

Preserve the existing configuration, including:

- `MONDAY_API_TOKEN`
- `OPENAI_API_KEY`
- `OPENAI_MODEL`
- `OPENAI_TIMEOUT_MS`
- `PORT`
- `DEFAULT_BOARD_ID`
- `BOARD_ITEM_DELAY_MS`
- `MONDAY_SIGNING_SECRET`

Do not hardcode secrets.

Validate monday.com JWTs according to the existing implementation and the current monday.com authentication requirements.

Ensure both feature routes are protected appropriately. Test missing secrets, invalid tokens, and malformed requests.

Consolidate configuration loading only after verifying how monday.com code supplies the variables. Do not assume that local environment behavior is identical to the deployed environment.

## 8. Scalability and Extensibility Requirements

The architecture must make future additions straightforward.

For a new automation, the expected process should be:

1. Create a new feature module.
2. Implement its service and request/response schemas.
3. Add a dedicated FastAPI router and route.
4. Register the router centrally.
5. Add unit and routing tests.
6. Add a corresponding monday.com action block if the feature is independently selectable.
7. Connect the block to the existing deployment and its dedicated subroute.
8. Configure only the additional environment variables that the feature genuinely requires.
9. Deploy and validate without changing existing feature behavior.

Shared infrastructure should be reused without coupling unrelated feature logic.

Do not make every new automation dependent on Company Enrichment or Customer Name Split.

Design for independent testing, clear failure isolation, and feature-specific logs.

Keep a single deployment for now. Do not prematurely introduce microservices. If workload, reliability, or scaling requirements later justify separate workers or services, document the migration path.

## 9. Execution Reliability

Review the existing Company Enrichment background-thread behavior.

If the application acknowledges a request before processing has actually completed, determine whether the current monday.com action is synchronous or asynchronous.

For lengthy operations, evaluate monday.com's asynchronous action-block mechanism, including its callback contract. Do not claim an action succeeded before its actual result is known.

Do not introduce a queue or persistent job store automatically. First determine whether the platform's async action mechanism is sufficient for the current workload and whether work must survive process restarts.

Keep this reliability improvement separate from the framework refactor where possible.

## 10. Testing and Acceptance Criteria

Run all existing tests and add tests covering:

- Company Enrichment through `/`.
- Company Enrichment through `/company-enrichment`.
- Customer Name Split through `/customer-name-split`.
- The alternative `/monday/split-name` route.
- Correct routing without relying on board IDs alone.
- Existing Kunden and Warm Lead behavior.
- Invalid and missing authentication.
- Malformed payloads and unknown routes.
- Shared logging and feature identification.
- Environment-variable loading.
- Regression of existing enrichment functionality.
- Independence of feature modules.

Mock external monday.com and AI API calls in automated tests.

The integration must not write to real customer boards during automated tests.

Acceptance requires:

- FastAPI is the only HTTP framework.
- Flask and `a2wsgi` are removed if no longer needed anywhere in the application.
- All existing Company Enrichment behavior is preserved.
- Both automation features work through the same deployment.
- Each block routes to the correct endpoint.
- The full test suite passes.
- The actual monday.com feature configuration has been verified.
- Rollback instructions are documented.

## 11. Deployment and Deliverables

Deploy through the existing monday.com app and deployment workflow, preferably using a draft version for validation before promotion.

Test Company Enrichment first, then Customer Name Split. Inspect the actual monday.com request logs to confirm which route each block invokes.

Provide:

1. The revised architecture and file tree.
2. A list of files changed and why.
3. A description of the Flask-to-FastAPI refactor.
4. Test commands and actual results.
5. Confirmation that both action blocks use the same deployment.
6. The exact route/subroute configuration required in monday.com.
7. Required environment variables and security considerations.
8. Deployment, verification, and rollback steps.
9. Any unresolved risks or platform constraints.

Do not report the work as complete merely because local tests pass. Verify the real monday.com feature configuration and live routing.

**Priority order:** Preserve existing behavior → refactor to FastAPI only → verify routes and authentication → configure both monday.com action blocks → validate the unified deployment → document how to add future automations.