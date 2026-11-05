from fastapi import Request

def get_db(request: Request):
    with request.app.state.sessionfactory() as db:
        yield db