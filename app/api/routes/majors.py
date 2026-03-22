import logging
from fastapi import APIRouter, HTTPException, Query
from typing import List, Dict, Any, Optional
from app.repositories.majors_repository import MajorsRepository

logger = logging.getLogger(__name__)

router = APIRouter()
majors_repo = MajorsRepository()

@router.get("/search")
async def search_majors(
    q: str = Query(..., min_length=2, description="Search query (minimum 2 characters)"),
    limit: int = Query(10, ge=1, le=50, description="Maximum number of results")
) -> Dict[str, Any]:
    """
    Search majors by title or CIP code
    
    Returns a list of majors matching the search query.
    """
    try:
        results = await majors_repo.search_majors(
            query=q,
            limit=limit
        )
        
        return {
            "query": q,
            "results": results,
            "count": len(results)
        }
        
    except Exception as e:
        logger.error(f"Majors search failed: {str(e)}")
        raise HTTPException(status_code=500, detail="Search failed")

@router.get("/{major_id}")
async def get_major(major_id: str) -> Dict[str, Any]:
    """Get a specific major by ID"""
    try:
        major = await majors_repo.get_major_by_id(major_id)
        
        if not major:
            raise HTTPException(status_code=404, detail="Major not found")
        
        return {"major": major}
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get major: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to get major")

@router.get("/cip/{cip_code}")
async def get_major_by_cip(cip_code: str) -> Dict[str, Any]:
    """Get a major by CIP code"""
    try:
        major = await majors_repo.get_major_by_cip_code(cip_code)
        
        if not major:
            raise HTTPException(status_code=404, detail="Major not found")
        
        return {"major": major}
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get major: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to get major")

@router.get("/family/{cip_family}")
async def get_majors_by_family(
    cip_family: str,
    limit: int = Query(50, ge=1, le=200, description="Maximum number of results")
) -> Dict[str, Any]:
    """Get majors by CIP family"""
    try:
        majors = await majors_repo.get_majors_by_family(
            cip_family=cip_family,
            limit=limit
        )
        
        return {
            "cip_family": cip_family,
            "majors": majors,
            "count": len(majors)
        }
        
    except Exception as e:
        logger.error(f"Failed to get majors: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to get majors")

@router.get("/")
async def get_major_stats() -> Dict[str, Any]:
    """Get majors directory statistics"""
    try:
        total_count = await majors_repo.get_major_count()
        
        return {
            "total_majors": total_count,
            "message": "Majors Directory API"
        }
        
    except Exception as e:
        logger.error(f"Failed to get majors stats: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to get stats")