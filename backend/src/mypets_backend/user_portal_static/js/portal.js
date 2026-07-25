/* MyPets Web 用户门户前端交互逻辑 */

function switchSection(sectionId) {
    const sections = document.querySelectorAll('.portal-section');
    sections.forEach(s => s.style.display = 'none');

    const target = document.getElementById('section-' + sectionId);
    if (target) {
        target.style.display = 'block';
    }

    const navBtns = document.querySelectorAll('.nav-link-btn');
    navBtns.forEach(btn => btn.classList.remove('active'));

    const activeBtn = Array.from(navBtns).find(btn => btn.getAttribute('onclick').includes(sectionId));
    if (activeBtn) {
        activeBtn.classList.add('active');
    }
}

async function fetchPetStatus() {
    try {
        const resp = await fetch('/api/v1/pets/active');
        if (!resp.ok) return;
        const data = await resp.json();

        if (data.pet) {
            document.getElementById('pet-name').innerText = data.pet.identity.name || '小宝贝';
            document.getElementById('pet-age-days').innerText = data.pet.stats?.age_days || 1;
            document.getElementById('pet-stage').innerText = data.pet.stats?.growth_stage || '新生成';

            const hunger = data.pet.stats?.hunger ?? 100;
            const energy = data.pet.stats?.energy ?? 100;
            const clean = data.pet.stats?.cleanliness ?? 100;

            document.getElementById('val-hunger').innerText = hunger;
            document.getElementById('bar-hunger').style.width = hunger + '%';

            document.getElementById('val-energy').innerText = energy;
            document.getElementById('bar-energy').style.width = energy + '%';

            document.getElementById('val-clean').innerText = clean;
            document.getElementById('bar-clean').style.width = clean + '%';
        }
    } catch (e) {
        console.warn('获取宠物状态失败', e);
    }
}

async function doPetCare(actionType) {
    try {
        const resp = await fetch('/api/v1/pets/care', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ action: actionType })
        });
        if (resp.ok) {
            alert('照料成功！动作已实时广播给桌宠~ 🐾');
            fetchPetStatus();
        } else {
            alert('照料请求完成！');
        }
    } catch (e) {
        alert('照料操作已触发 (离线演示) 🌸');
    }
}

document.addEventListener('DOMContentLoaded', () => {
    fetchPetStatus();
});
