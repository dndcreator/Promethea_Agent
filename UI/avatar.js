class AvatarManager {
    constructor() {
        this.placeholder = document.getElementById('avatarPlaceholder');
        this.uploadInput = document.getElementById('avatarUpload');
        this.avatarImage = document.getElementById('avatarImage');
        this.avatarIcon = document.getElementById('avatarIcon');
        this.avatarHint = document.getElementById('avatarHint');
        this.removeBtn = document.getElementById('removeAvatarBtn');
        
        this.bindEvents();
        this.loadAvatar();
    }
    
    bindEvents() {
        this.placeholder.addEventListener('click', (e) => {
            if (e.target !== this.removeBtn) {
                this.uploadInput.click();
            }
        });
        
        this.uploadInput.addEventListener('change', (e) => {
            const file = e.target.files[0];
            if (file && file.type.startsWith('image/')) {
                this.setAvatar(file);
            }
        });
        
        this.removeBtn.addEventListener('click', (e) => {
            e.stopPropagation();
            this.removeAvatar();
        });
    }
    
    setAvatar(file) {
        const reader = new FileReader();
        reader.onload = (e) => {
            const imageData = e.target.result;
            
            this.avatarImage.src = imageData;
            this.avatarImage.style.display = 'block';
            this.avatarIcon.style.display = 'none';
            this.avatarHint.style.display = 'none';
            this.removeBtn.style.display = 'flex';
            
            localStorage.setItem('avatar_image', imageData);
            
            console.info('Avatar updated');
        };
        reader.readAsDataURL(file);
    }
    
    removeAvatar() {
        this.avatarImage.style.display = 'none';
        this.avatarImage.src = '';
        this.avatarIcon.style.display = 'block';
        this.avatarHint.style.display = 'block';
        this.removeBtn.style.display = 'none';
        
        localStorage.removeItem('avatar_image');
        
        console.info('Avatar removed');
    }
    
    loadAvatar() {
        const savedImage = localStorage.getItem('avatar_image');
        if (savedImage) {
            this.avatarImage.src = savedImage;
            this.avatarImage.style.display = 'block';
            this.avatarIcon.style.display = 'none';
            this.avatarHint.style.display = 'none';
            this.removeBtn.style.display = 'flex';
        }
    }
}

