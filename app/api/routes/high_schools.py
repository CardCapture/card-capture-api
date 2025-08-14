from fastapi import APIRouter, HTTPException, Query
from typing import List, Dict, Any, Optional
from app.repositories.high_schools_repository import HighSchoolsRepository

router = APIRouter()
high_schools_repo = HighSchoolsRepository()

@router.get("/search")
async def search_high_schools(
    q: str = Query(..., min_length=2, description="Search query (minimum 2 characters)"),
    limit: int = Query(10, ge=1, le=50, description="Maximum number of results"),
    state: Optional[str] = Query(None, description="Filter by state (2-letter code)")
) -> Dict[str, Any]:
    """
    Search high schools by name
    
    Returns a list of schools matching the search query.
    """
    try:
        results = await high_schools_repo.search_schools(
            query=q,
            limit=limit,
            state=state
        )
        
        return {
            "query": q,
            "results": results,
            "count": len(results)
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Search failed: {str(e)}")

@router.get("/{school_id}")
async def get_school(school_id: str) -> Dict[str, Any]:
    """Get a specific school by ID"""
    try:
        school = await high_schools_repo.get_school_by_id(school_id)
        
        if not school:
            raise HTTPException(status_code=404, detail="School not found")
        
        return {"school": school}
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get school: {str(e)}")

@router.get("/state/{state}")
async def get_schools_by_state(
    state: str,
    limit: int = Query(100, ge=1, le=500, description="Maximum number of results")
) -> Dict[str, Any]:
    """Get schools by state"""
    try:
        # Validate state code
        if len(state) != 2:
            raise HTTPException(status_code=400, detail="State must be a 2-letter code")
        
        schools = await high_schools_repo.get_schools_by_state(
            state=state.upper(),
            limit=limit
        )
        
        return {
            "state": state.upper(),
            "schools": schools,
            "count": len(schools)
        }
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get schools: {str(e)}")

@router.get("/")
async def get_school_stats() -> Dict[str, Any]:
    """Get high school directory statistics"""
    try:
        total_count = await high_schools_repo.get_school_count()
        
        return {
            "total_schools": total_count,
            "message": "High Schools Directory API"
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get stats: {str(e)}")