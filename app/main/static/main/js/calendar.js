const openPopUp = document.getElementById('open_pop_up')
const closePopUp = document.getElementById('close_pop_up')
const closePopUpBtn = document.getElementById('close_pop_up_btn')
const popUp = document.getElementById('pop_up')

openPopUp.addEventListener('click', function(e){
    e.preventDefault();
    popUp.classList.add('active')
})

closePopUp.addEventListener('click', () => {
    popUp.classList.remove('active')
})

closePopUpBtn.addEventListener('click', () => {
    popUp.classList.remove('active')
})