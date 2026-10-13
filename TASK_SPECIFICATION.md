# Final task: Project Management Software (backend)

You will build a web-based Project Management Software - a tool that helps people organize and collaborate on projects. Users can sign up, log in, and create new projects, each with its own name and description. The person who creates a project becomes its owner and can invite others to join as participants. Owners have full control over their projects: they can edit details, add or remove documents (like images, PDFs or Word files), invite or remove participants, and even delete the project if needed. Participants can view and update project details and documents, but they cannot delete the project or manage other users.

For each project, users can upload important files, update or delete them, and download any documents they have access to. All documents are stored securely. Owners can easily share access to their projects by sending invitations, ensuring that only invited users can see and work on a project. Every user can see a list of all projects they have access to, along with all the details and documents for each one.

In short, you are creating a simple but powerful tool for managing projects, working together with others, and keeping all project documents organized in one place.

## Ownership

When working on this project, you are both a developer and a product owner - you are encouraged to add new features, enhance the design, or implement advanced capabilities if you wish. If you're unsure about anything or want to discuss your ideas, you can always reach out to your mentor for guidance.

## Tech Stack

- **Programming Language:** Python 3.12+
- **Testing Framework:** Pytest
- **Web Framework:** FastAPI
- **Database:** PostgreSQL (with SQLAlchemy as ORM)
- **Containerization:** Docker
- **CI/CD:** GitHub Actions/Gitlab CI
- **Cloud:** AWS (optional)
- **Data Validation:** Pydantic
- **Packaging & Dependency Management:** pyproject.toml, Poetry, tox, uv

## Required Functionality

- User authentication (login, registration)
- All the business logic requests should be authorized via JWT (including resolving access permissions). JWT should last 1 hour
- Manage projects (create, retrieve, update, remove)
- Manage documents belonging to projects (upload, retrieve, replace, remove)
- Share projects with other users (access control)
- Run application and store documents locally

## Required API Endpoints

### Authentication

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/auth` | Create a new user (login, password) |
| POST | `/login` | User login (login, password) |

### Projects

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/projects` | Create a new project (name, description). The creator becomes the owner (admin). |
| GET | `/projects` | List all projects accessible to the user (details + documents). |
| GET | `/projects/<project_id>/info` | Get project details (if user has access). |
| PUT | `/projects/<project_id>/info` | Update project details (name, description). |
| DELETE | `/projects/<project_id>` | Delete a project (owner only; deletes associated documents). |

### Documents

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/projects/<project_id>/documents` | List all documents for a project. |
| POST | `/projects/<project_id>/documents` | Upload document(s) to a project. |
| GET | `/documents/<document_id>` | Download a document (if user has access). |
| PUT | `/documents/<document_id>` | Update a document. |
| DELETE | `/documents/<document_id>` | Delete a document from the project. |

### Sharing & Access

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/projects/<project_id>/invite?user=<login>` | Grant project access to another user (owner only). |

## Advanced features

You are encouraged to go beyond the basic requirements and make your project as sophisticated as you wish, depending on your time and knowledge. You can bring your own ideas for features and technical improvements to the system. Here are some suggestions for advanced enhancements:

- Deploy and run your application on AWS using ECS or EC2.
- Use an S3 bucket for document storage.
- Create AWS Lambda to automatically modify or update uploaded documents, for example resizing image files after they are added to S3.
- Use GitHub Actions / GitLab CI not only for running unit tests, but also for scanning your code for vulnerabilities, running linter checks, building Docker image, pushing it to registry, and/or automatically deploying your application to AWS and more.

Feel free to innovate and add features that interest you. If you have questions or want to discuss your ideas, your mentor is always available to help.

## Gen AI usage

You are allowed - and even encouraged - to use generative AI tools to help with your project development. However, you are fully responsible for the work you present. Make sure you understand every part of the code you submit: what it does, how it works, and why you chose to implement it that way. Using AI is a great way to learn, but true understanding is essential for your growth as a developer.
