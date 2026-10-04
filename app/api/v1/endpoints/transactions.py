from fastapi import APIRouter

router = APIRouter()

@router.get("/", summary="Historial de transacciones")
def get_transactions():
    return {"msg": "Endpoint de historial de transacciones"}